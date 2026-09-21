from __future__ import annotations

import asyncio
import time

from config.settings import ALERT_MEMORY_MB, ALERT_MEMORY_WINDOW_SECONDS
from core.monitoring.alerts import alert_manager
from core.monitoring.metrics import metrics


async def start_health_monitor(interval_seconds: int = 60) -> None:
    high_since: float | None = None
    while True:
        await asyncio.sleep(interval_seconds)
        memory_mb = metrics.record_memory_mb()
        if memory_mb > ALERT_MEMORY_MB:
            high_since = high_since or time.monotonic()
            if time.monotonic() - high_since >= ALERT_MEMORY_WINDOW_SECONDS:
                await alert_manager.send(
                    "memory_high",
                    "Process memory is above the configured warning threshold.",
                    memory_mb=memory_mb,
                    threshold_mb=ALERT_MEMORY_MB,
                    window_seconds=ALERT_MEMORY_WINDOW_SECONDS,
                )
        else:
            high_since = None
