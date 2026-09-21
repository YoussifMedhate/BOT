from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from config.settings import RATE_LIMIT_MAX_EVENTS, RATE_LIMIT_WINDOW_SECONDS


class InMemoryRateLimiter:
    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: int) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_events:
            return False
        hits.append(now)
        return True


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limiter: InMemoryRateLimiter | None = None):
        self.limiter = limiter or InMemoryRateLimiter(
            RATE_LIMIT_MAX_EVENTS,
            RATE_LIMIT_WINDOW_SECONDS,
        )

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        if self.limiter.is_allowed(user.id):
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer("من فضلك انتظر لحظة قبل إرسال طلب جديد.")
        elif isinstance(event, CallbackQuery):
            await event.answer("من فضلك انتظر لحظة.", show_alert=False)
        return None
