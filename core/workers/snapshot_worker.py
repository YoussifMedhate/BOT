from __future__ import annotations

import asyncio
import logging

from core.application.analytics_service import analytics_service

logger = logging.getLogger(__name__)


async def start_snapshot_worker(interval_seconds: int = 3600) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await analytics_service.rebuild_daily_snapshot()
            logger.info("Daily analytics snapshot rebuilt", extra={"event": "snapshot_rebuilt"})
        except Exception:
            logger.exception("Daily analytics snapshot failed", extra={"event": "snapshot_failed"})
