from __future__ import annotations

import logging
import time
from typing import Any

from config.settings import ADMIN_IDS

logger = logging.getLogger(__name__)


class AlertManager:
    def __init__(self, bot: Any | None = None, cooldown_seconds: int = 300):
        self.bot = bot
        self.cooldown_seconds = cooldown_seconds
        self._last_sent: dict[str, float] = {}

    def bind_bot(self, bot: Any) -> None:
        self.bot = bot

    def _allowed(self, key: str) -> bool:
        now = time.monotonic()
        last_sent = self._last_sent.get(key, 0)
        if now - last_sent < self.cooldown_seconds:
            return False
        self._last_sent[key] = now
        return True

    async def send(self, key: str, text: str, **fields: Any) -> None:
        logger.warning(text, extra={"event": key, **fields})
        if not self.bot or not ADMIN_IDS or not self._allowed(key):
            return

        for admin_id in ADMIN_IDS:
            try:
                await self.bot.send_message(chat_id=admin_id, text=text)
            except Exception as exc:
                logger.error(
                    "Failed to send admin alert",
                    extra={"event": "alert_send_failed", "admin_id": admin_id, "error": str(exc)},
                )


alert_manager = AlertManager()
