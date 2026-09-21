from __future__ import annotations

import time
from typing import Any

from aiogram.types import CallbackQuery, Message, User

from core.database import db
from core.domain.analytics import AnalyticsEvent, DashboardSummary
from core.infrastructure.analytics_repository import AnalyticsRepository
from core.monitoring.metrics import metrics
from core.workers.analytics_writer import AnalyticsQueueWriter


def _user_fields(user: User | None) -> dict[str, Any]:
    if user is None:
        return {}
    return {
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
    }


class AnalyticsService:
    def __init__(self, writer: AnalyticsQueueWriter):
        self.writer = writer

    async def start(self) -> None:
        await self.writer.start()

    async def stop(self) -> None:
        await self.writer.stop()

    async def track_event(self, event: AnalyticsEvent) -> bool:
        return await self.writer.enqueue(event)

    async def track_message_received(self, message: Message, source: str) -> bool:
        return await self.track_event(
            AnalyticsEvent(
                event_type="message_received",
                source=source,
                chat_id=message.chat.id,
                message_id=message.message_id,
                payload={"text": message.text[:128] if message.text else None},
                **_user_fields(message.from_user),
            )
        )

    async def track_callback_received(self, callback: CallbackQuery, source: str) -> bool:
        message = callback.message
        return await self.track_event(
            AnalyticsEvent(
                event_type="callback_received",
                source=source,
                chat_id=getattr(message.chat, "id", None) if message else None,
                message_id=getattr(message, "message_id", None) if message else None,
                payload={"data": callback.data},
                **_user_fields(callback.from_user),
            )
        )

    async def track_menu_open(self, message: Message, source: str, menu_name: str) -> bool:
        return await self.track_event(
            AnalyticsEvent(
                event_type="menu_open",
                source=source,
                chat_id=message.chat.id,
                message_id=message.message_id,
                menu_name=menu_name,
                **_user_fields(message.from_user),
            )
        )

    async def track_material_view(
        self,
        message: Message,
        source: str,
        material: dict[str, Any],
    ) -> bool:
        material_id = material.get("id")
        if material_id is None:
            return False
        return await self.track_event(
            AnalyticsEvent(
                event_type="material_view",
                source=source,
                chat_id=message.chat.id,
                message_id=message.message_id,
                menu_name=material.get("menu_name"),
                material_id=int(material_id),
                payload={
                    "file_type": material.get("file_type"),
                    "is_text": material.get("channel_id") == "TEXT",
                },
                **_user_fields(message.from_user),
            )
        )

    async def dashboard_summary(self, top_limit: int = 10) -> DashboardSummary:
        started = time.perf_counter()
        summary = await self.writer.repository.dashboard_summary(top_limit)
        metrics.record_dashboard_query_ms((time.perf_counter() - started) * 1000)
        return summary

    async def rebuild_daily_snapshot(self) -> None:
        await self.writer.repository.rebuild_daily_snapshot()


analytics_repository = AnalyticsRepository(db)
analytics_writer = AnalyticsQueueWriter(analytics_repository)
analytics_service = AnalyticsService(analytics_writer)
