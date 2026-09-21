from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from core.application.analytics_service import analytics_service
from core.monitoring.metrics import metrics

logger = logging.getLogger(__name__)


class AnalyticsMiddleware(BaseMiddleware):
    def __init__(self, source: str):
        self.source = source

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        try:
            if isinstance(event, Message):
                await analytics_service.track_message_received(event, self.source)
            elif isinstance(event, CallbackQuery):
                await analytics_service.track_callback_received(event, self.source)
        except Exception:
            logger.exception(
                "Failed to enqueue analytics event",
                extra={"event": "analytics_enqueue_failed", "source": self.source},
            )

        try:
            return await handler(event, data)
        finally:
            metrics.record_bot_response_ms((time.perf_counter() - started) * 1000)
