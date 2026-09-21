from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta

from aiogram import Bot

from admin_bot.handlers.backup_ops import send_backup_to_channel
from config.settings import (
    BACKUP_CHANNEL_ID,
    BACKUP_INTERVAL_HOURS,
    BACKUP_RETENTION_DAILY,
    BACKUP_RETENTION_MONTHLY,
    BACKUP_RETENTION_WEEKLY,
)
from core.monitoring.alerts import alert_manager

logger = logging.getLogger(__name__)

# Local ledger: one JSON line per backup → {message_id, sent_at (ISO 8601)}
_LEDGER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
    "backup_ledger.jsonl",
)


# ─── Ledger helpers ──────────────────────────────────────────────


def _load_ledger() -> list[dict]:
    """Return all ledger entries sorted oldest-first."""
    if not os.path.exists(_LEDGER_PATH):
        return []
    entries: list[dict] = []
    with open(_LEDGER_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    entries.sort(key=lambda e: e.get("sent_at", ""))
    return entries


def _save_ledger(entries: list[dict]) -> None:
    """Rewrite the ledger file with the given entries."""
    os.makedirs(os.path.dirname(_LEDGER_PATH), exist_ok=True)
    with open(_LEDGER_PATH, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _append_ledger(message_id: int, sent_at: datetime) -> None:
    """Append a single new backup record to the ledger."""
    os.makedirs(os.path.dirname(_LEDGER_PATH), exist_ok=True)
    record = {"message_id": message_id, "sent_at": sent_at.astimezone(UTC).isoformat()}
    with open(_LEDGER_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ─── Retention logic ─────────────────────────────────────────────


def _select_entries_to_keep(entries: list[dict]) -> set[int]:
    """
    Apply the 7-daily / 4-weekly / 12-monthly retention policy.

    Strategy (newest-first scan):
    - Keep the most recent BACKUP_RETENTION_DAILY entries unconditionally
      (daily tier).
    - From older entries keep one per ISO calendar week for the last
      BACKUP_RETENTION_WEEKLY weeks (weekly tier).
    - From still-older entries keep one per calendar month for the last
      BACKUP_RETENTION_MONTHLY months (monthly tier).
    - Discard everything else.
    """
    if not entries:
        return set()

    keep: set[int] = set()
    seen_weeks: set[str] = set()
    seen_months: set[str] = set()

    # Work newest → oldest
    for entry in reversed(entries):
        msg_id = entry.get("message_id")
        if msg_id is None:
            continue
        try:
            dt = datetime.fromisoformat(entry["sent_at"])
        except (KeyError, ValueError):
            keep.add(msg_id)  # keep entries with unparseable dates to be safe
            continue

        # Daily tier: unconditionally keep the N most recent
        if len(keep) < BACKUP_RETENTION_DAILY:
            keep.add(msg_id)
            continue

        # Weekly tier: one entry per ISO week, up to BACKUP_RETENTION_WEEKLY weeks
        week_key = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        if len(seen_weeks) < BACKUP_RETENTION_WEEKLY and week_key not in seen_weeks:
            seen_weeks.add(week_key)
            keep.add(msg_id)
            continue

        # Monthly tier: one entry per calendar month, up to BACKUP_RETENTION_MONTHLY
        month_key = f"{dt.year}-{dt.month:02d}"
        if len(seen_months) < BACKUP_RETENTION_MONTHLY and month_key not in seen_months:
            seen_months.add(month_key)
            keep.add(msg_id)
            continue

        # Falls outside all tiers → will be deleted

    return keep


async def prune_old_backups(bot: Bot) -> None:
    """
    Delete backup messages from the channel that fall outside the retention
    policy, and update the local ledger accordingly.

    Policy: 7 daily + 4 weekly + 12 monthly  (all configurable via env vars).
    """
    entries = _load_ledger()
    if not entries:
        return

    keep_ids = _select_entries_to_keep(entries)
    to_delete = [e for e in entries if e.get("message_id") not in keep_ids]

    if not to_delete:
        return

    deleted_ids: set[int] = set()
    for entry in to_delete:
        msg_id = entry.get("message_id")
        if msg_id is None:
            continue
        try:
            await bot.delete_message(chat_id=BACKUP_CHANNEL_ID, message_id=msg_id)
            deleted_ids.add(msg_id)
            logger.info(
                "Deleted old backup message",
                extra={"event": "backup_pruned", "message_id": msg_id, "sent_at": entry.get("sent_at")},
            )
        except Exception as exc:
            # Message may already be deleted or too old for Telegram to delete — log and continue
            logger.warning(
                "Could not delete backup message from channel",
                extra={"event": "backup_prune_skip", "message_id": msg_id, "error": str(exc)},
            )
            # Still remove from ledger so we don't retry forever
            deleted_ids.add(msg_id)

    # Rewrite ledger keeping only the surviving entries
    surviving = [e for e in entries if e.get("message_id") not in deleted_ids]
    _save_ledger(surviving)
    logger.info(
        "Backup retention complete",
        extra={"event": "backup_retention_done", "deleted": len(deleted_ids), "kept": len(surviving)},
    )


# ─── Scheduler ───────────────────────────────────────────────────


async def start_backup_scheduler(bot: Bot) -> None:
    """Background task that sends automatic backups every BACKUP_INTERVAL_HOURS
    and then prunes old backups according to the retention policy."""
    interval = BACKUP_INTERVAL_HOURS * 3600  # seconds

    while True:
        await asyncio.sleep(interval)
        now = datetime.now(UTC)
        try:
            logger.info("Running scheduled backup", extra={"event": "backup_scheduled_started"})
            message = await _send_backup_and_record(bot, now)
            logger.info(
                "Scheduled backup sent successfully",
                extra={"event": "backup_scheduled_ok", "message_id": message.message_id},
            )
        except Exception as e:
            logger.exception("Scheduled backup failed", extra={"event": "backup_scheduled_failed"})
            await alert_manager.send(
                "backup_failed",
                "Scheduled database backup failed.",
                error=str(e),
            )
            continue  # skip pruning if the backup itself failed

        # Prune old backups after a successful backup
        try:
            await prune_old_backups(bot)
        except Exception:
            logger.exception("Backup retention pruning failed", extra={"event": "backup_prune_failed"})


async def _send_backup_and_record(bot: Bot, sent_at: datetime):
    """Send a backup to the channel and record its message_id in the ledger."""
    from admin_bot.handlers.backup_ops import create_backup_zip
    from aiogram.types import BufferedInputFile

    zip_filename, zip_bytes = await create_backup_zip()
    caption = f"💾 باك أب تلقائي\n📅 {sent_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    input_file = BufferedInputFile(zip_bytes, filename=zip_filename)

    result = await bot.send_document(
        chat_id=BACKUP_CHANNEL_ID,
        document=input_file,
        caption=caption,
    )
    logger.info("Backup sent to channel", extra={"event": "backup_sent"})

    # Record in ledger for future retention decisions
    _append_ledger(result.message_id, sent_at)
    return result
