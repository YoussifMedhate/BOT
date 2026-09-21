from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True)
class AnalyticsEvent:
    event_type: str
    source: str
    occurred_at: datetime = field(default_factory=utc_now)
    user_id: int | None = None
    username: str | None = None
    full_name: str | None = None
    chat_id: int | None = None
    message_id: int | None = None
    menu_name: str | None = None
    material_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_type or len(self.event_type) > 64:
            raise ValueError("event_type must be 1-64 characters")
        if not self.source or len(self.source) > 64:
            raise ValueError("source must be 1-64 characters")
        if self.user_id is not None and self.user_id <= 0:
            raise ValueError("user_id must be positive")
        if self.material_id is not None and self.material_id <= 0:
            raise ValueError("material_id must be positive")
        _require_aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True)
class MaterialStat:
    material_id: int
    menu_name: str | None
    view_count: int
    last_viewed_at: datetime | None


@dataclass(frozen=True)
class DashboardSummary:
    active_users_24h: int
    total_events_24h: int
    menu_views_24h: int
    material_views_24h: int
    top_materials: list[MaterialStat]
