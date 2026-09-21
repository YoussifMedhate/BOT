from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from dataclasses import dataclass

from config.settings import (
    ALERT_DB_WRITE_P95_MS,
    ALERT_QUEUE_THRESHOLD_RATIO,
    ANALYTICS_BATCH_SIZE,
    ANALYTICS_DEAD_LETTER_PATH,
    ANALYTICS_FLUSH_INTERVAL_SECONDS,
    ANALYTICS_QUEUE_MAX_SIZE,
)
from core.domain.analytics import AnalyticsEvent
from core.infrastructure.analytics_repository import AnalyticsRepository
from core.infrastructure.blocking import run_blocking
from core.monitoring.alerts import alert_manager
from core.monitoring.metrics import metrics

logger = logging.getLogger(__name__)


class AnalyticsQueueWriter:
    def __init__(
        self,
        repository: AnalyticsRepository,
        max_size: int = ANALYTICS_QUEUE_MAX_SIZE,
        flush_interval_seconds: float = ANALYTICS_FLUSH_INTERVAL_SECONDS,
        batch_size: int = ANALYTICS_BATCH_SIZE,
        dead_letter_path: str = ANALYTICS_DEAD_LETTER_PATH,
    ):
        self.repository = repository
        self.flush_interval_seconds = flush_interval_seconds
        self.batch_size = batch_size
        self.dead_letter_path = dead_letter_path
        self._stop_signal = object()
        self.queue: asyncio.Queue[AnalyticsEvent | object] = asyncio.Queue(maxsize=max_size)
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="analytics-writer")
        logger.info("Analytics writer started", extra={"event": "analytics_writer_started"})

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            await self.queue.put(self._stop_signal)
            await self._task
            self._task = None
        logger.info("Analytics writer stopped", extra={"event": "analytics_writer_stopped"})

    async def enqueue(self, event: AnalyticsEvent) -> bool:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            await self._write_dead_letter(event, "queue_full")
            await alert_manager.send(
                "queue_full",
                "Analytics queue is full; event moved to dead-letter log.",
                queue_length=self.queue.qsize(),
                queue_max_size=self.queue.maxsize,
            )
            return False

        queue_length = self.queue.qsize()
        metrics.set_queue_length(queue_length)
        if queue_length >= int(self.queue.maxsize * ALERT_QUEUE_THRESHOLD_RATIO):
            await alert_manager.send(
                "queue_high",
                "Analytics queue is above the configured warning threshold.",
                queue_length=queue_length,
                queue_max_size=self.queue.maxsize,
                threshold_ratio=ALERT_QUEUE_THRESHOLD_RATIO,
            )
        return True

    async def _run(self) -> None:
        while not self._stopping.is_set() or not self.queue.empty():
            batch = await self._collect_batch()
            if not batch:
                continue
            await self._flush(batch)

    async def _collect_batch(self) -> list[AnalyticsEvent]:
        batch: list[AnalyticsEvent] = []

        if self._stopping.is_set() and self.queue.empty():
            return batch

        try:
            first = await asyncio.wait_for(
                self.queue.get(),
                timeout=self.flush_interval_seconds,
            )
        except TimeoutError:
            return batch

        if first is self._stop_signal:
            self.queue.task_done()
            return batch

        assert isinstance(first, AnalyticsEvent)
        batch.append(first)
        while len(batch) < self.batch_size:
            try:
                item = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is self._stop_signal:
                self.queue.task_done()
                break
            assert isinstance(item, AnalyticsEvent)
            batch.append(item)
        return batch

    async def _flush(self, batch: Sequence[AnalyticsEvent]) -> None:
        try:
            write_ms = await self.repository.record_events(batch)
            metrics.record_queue_write_ms(write_ms)
            metrics.set_queue_length(self.queue.qsize())

            if metrics.queue_write_ms.percentile(95) > ALERT_DB_WRITE_P95_MS:
                await alert_manager.send(
                    "db_write_slow",
                    "Analytics database writes are above the configured P95 threshold.",
                    db_write_p95_ms=metrics.queue_write_ms.percentile(95),
                    threshold_ms=ALERT_DB_WRITE_P95_MS,
                )
        except Exception as exc:
            logger.exception(
                "Failed to flush analytics batch",
                extra={"event": "analytics_flush_failed", "batch_size": len(batch)},
            )
            for event in batch:
                await self._write_dead_letter(event, f"flush_failed:{exc}")
        finally:
            for _ in batch:
                self.queue.task_done()
            metrics.set_queue_length(self.queue.qsize())

    async def _write_dead_letter(self, event: AnalyticsEvent, reason: str) -> None:
        line = {
            "reason": reason,
            "event_type": event.event_type,
            "source": event.source,
            "user_id": event.user_id,
            "chat_id": event.chat_id,
            "message_id": event.message_id,
            "menu_name": event.menu_name,
            "material_id": event.material_id,
            "payload": event.payload,
            "occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
        }
        await run_blocking(self._append_json_line, line)

    def _append_json_line(self, payload: dict) -> None:
        directory = os.path.dirname(self.dead_letter_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.dead_letter_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


@dataclass
class ReplayResult:
    """Summary returned by replay_dead_letters()."""
    replayed: int    # events successfully re-enqueued
    skipped: int     # malformed lines that could not be parsed
    dropped: int     # events skipped because the queue was still full


async def replay_dead_letters(
    writer: "AnalyticsQueueWriter",
    dead_letter_path: str = ANALYTICS_DEAD_LETTER_PATH,
) -> ReplayResult:
    """
    Read every entry from the dead-letter JSONL file, reconstruct the
    original AnalyticsEvent objects, and re-enqueue them into *writer*.

    Lines that cannot be parsed are counted as *skipped*.
    Events that cannot be enqueued (queue still full) are counted as *dropped*
    and written back to a temporary overflow file that replaces the original.

    On a full successful replay the dead-letter file is truncated to zero
    bytes (not deleted, so the path remains stable for future writes).
    """
    if not os.path.exists(dead_letter_path):
        return ReplayResult(replayed=0, skipped=0, dropped=0)

    lines = await run_blocking(_read_lines, dead_letter_path)
    if not lines:
        return ReplayResult(replayed=0, skipped=0, dropped=0)

    replayed = 0
    skipped = 0
    overflow: list[str] = []  # lines that could not be re-enqueued

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            event = _dict_to_event(data)
        except Exception:
            logger.warning(
                "Dead letter line could not be parsed — skipping",
                extra={"event": "dead_letter_parse_error", "line": raw[:200]},
            )
            skipped += 1
            continue

        enqueued = await writer.enqueue(event)
        if enqueued:
            replayed += 1
        else:
            # Queue is still full — preserve this entry for the next replay
            overflow.append(raw)

    dropped = len(overflow)
    await run_blocking(_write_overflow, dead_letter_path, overflow)

    logger.info(
        "Dead letter replay complete",
        extra={
            "event": "dead_letter_replay_done",
            "replayed": replayed,
            "skipped": skipped,
            "dropped": dropped,
        },
    )
    return ReplayResult(replayed=replayed, skipped=skipped, dropped=dropped)


def _read_lines(path: str) -> list[str]:
    """Read all lines from the dead-letter file (runs in thread pool)."""
    with open(path, encoding="utf-8") as fh:
        return fh.readlines()


def _write_overflow(path: str, lines: list[str]) -> None:
    """Rewrite the dead-letter file with only the lines that could not be replayed."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line if line.endswith("\n") else line + "\n")


def _dict_to_event(data: dict) -> AnalyticsEvent:
    """Reconstruct an AnalyticsEvent from a dead-letter dict."""
    occurred_at_raw = data.get("occurred_at")
    if occurred_at_raw:
        occurred_at = datetime.fromisoformat(occurred_at_raw)
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
    else:
        occurred_at = datetime.now(UTC)

    return AnalyticsEvent(
        event_type=data["event_type"],
        source=data.get("source", "replay"),
        user_id=data.get("user_id"),
        username=data.get("username"),
        full_name=data.get("full_name"),
        chat_id=data.get("chat_id"),
        message_id=data.get("message_id"),
        menu_name=data.get("menu_name"),
        material_id=data.get("material_id"),
        payload=data.get("payload") or {},
        occurred_at=occurred_at,
    )
