from __future__ import annotations

import json
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from core.database import Database
from core.domain.analytics import AnalyticsEvent, DashboardSummary, MaterialStat


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class AnalyticsRepository:
    def __init__(self, database: Database):
        self.database = database

    async def record_events(self, events: Sequence[AnalyticsEvent]) -> float:
        if not events:
            return 0.0

        started = time.perf_counter()
        rows = [
            (
                event.event_type,
                event.source,
                event.user_id,
                event.username,
                event.full_name,
                event.chat_id,
                event.message_id,
                event.menu_name,
                event.material_id,
                json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
                _to_iso(event.occurred_at),
            )
            for event in events
        ]

        async with self.database.write_lock:
            conn = await self.database.get_connection()
            try:
                await conn.execute("BEGIN IMMEDIATE")
                await conn.executemany(
                    """
                    INSERT INTO analytics_events (
                        event_type, source, user_id, username, full_name, chat_id,
                        message_id, menu_name, material_id, payload, occurred_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

                for event in events:
                    event_time = _to_iso(event.occurred_at)
                    if event.user_id is not None:
                        await conn.execute(
                            """
                            INSERT INTO user_sessions (
                                user_id, username, full_name, first_seen_at, last_seen_at, event_count
                            )
                            VALUES (?, ?, ?, ?, ?, 1)
                            ON CONFLICT(user_id) DO UPDATE SET
                                username = excluded.username,
                                full_name = excluded.full_name,
                                last_seen_at = excluded.last_seen_at,
                                event_count = user_sessions.event_count + 1
                            """,
                            (
                                event.user_id,
                                event.username,
                                event.full_name,
                                event_time,
                                event_time,
                            ),
                        )

                    if event.event_type == "material_view" and event.material_id is not None:
                        await conn.execute(
                            """
                            INSERT INTO analytics_material_stats (
                                material_id, menu_name, view_count, last_viewed_at
                            )
                            VALUES (?, ?, 1, ?)
                            ON CONFLICT(material_id) DO UPDATE SET
                                menu_name = COALESCE(excluded.menu_name, analytics_material_stats.menu_name),
                                view_count = analytics_material_stats.view_count + 1,
                                last_viewed_at = excluded.last_viewed_at
                            """,
                            (event.material_id, event.menu_name, event_time),
                        )

                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

        return (time.perf_counter() - started) * 1000

    async def get_top_materials(self, limit: int = 10) -> list[MaterialStat]:
        safe_limit = max(1, min(limit, 100))
        rows = await self.database.fetchall(
            """
            SELECT material_id, menu_name, view_count, last_viewed_at
            FROM analytics_material_stats
            ORDER BY view_count DESC, material_id ASC
            LIMIT ?
            """,
            (safe_limit,),
        )
        return [
            MaterialStat(
                material_id=row["material_id"],
                menu_name=row["menu_name"],
                view_count=row["view_count"],
                last_viewed_at=_parse_iso(row["last_viewed_at"]),
            )
            for row in rows
        ]

    async def active_users_since(self, since: datetime) -> int:
        row = await self.database.fetchone(
            "SELECT COUNT(*) AS count FROM user_sessions WHERE last_seen_at >= ?",
            (_to_iso(since),),
        )
        return int(row["count"]) if row else 0

    async def count_events_since(self, since: datetime, event_type: str | None = None) -> int:
        if event_type is None:
            row = await self.database.fetchone(
                "SELECT COUNT(*) AS count FROM analytics_events WHERE occurred_at >= ?",
                (_to_iso(since),),
            )
        else:
            row = await self.database.fetchone(
                """
                SELECT COUNT(*) AS count
                FROM analytics_events
                WHERE occurred_at >= ? AND event_type = ?
                """,
                (_to_iso(since), event_type),
            )
        return int(row["count"]) if row else 0

    async def dashboard_summary(self, top_limit: int = 10) -> DashboardSummary:
        since = datetime.now(UTC) - timedelta(hours=24)
        active_users = await self.active_users_since(since)
        total_events = await self.count_events_since(since)
        menu_views = await self.count_events_since(since, "menu_open")
        material_views = await self.count_events_since(since, "material_view")
        top_materials = await self.get_top_materials(top_limit)
        return DashboardSummary(
            active_users_24h=active_users,
            total_events_24h=total_events,
            menu_views_24h=menu_views,
            material_views_24h=material_views,
            top_materials=top_materials,
        )

    async def rebuild_daily_snapshot(self, day: datetime | None = None) -> None:
        target = day or datetime.now(UTC)
        day_start = target.astimezone(UTC).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        day_end = day_start + timedelta(days=1)
        params = (_to_iso(day_start), _to_iso(day_end))

        async with self.database.write_lock:
            conn = await self.database.get_connection()
            try:
                async with conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_events,
                        COUNT(DISTINCT user_id) AS active_users,
                        SUM(CASE WHEN event_type = 'menu_open' THEN 1 ELSE 0 END) AS menu_views,
                        SUM(CASE WHEN event_type = 'material_view' THEN 1 ELSE 0 END) AS material_views
                    FROM analytics_events
                    WHERE occurred_at >= ? AND occurred_at < ?
                    """,
                    params,
                ) as cursor:
                    row = await cursor.fetchone()

                if row is None:
                    raise RuntimeError("Daily snapshot aggregation query returned no row")
                await conn.execute(
                    """
                    INSERT INTO analytics_daily_snapshots (
                        day, active_users, total_events, menu_views, material_views
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(day) DO UPDATE SET
                        active_users = excluded.active_users,
                        total_events = excluded.total_events,
                        menu_views = excluded.menu_views,
                        material_views = excluded.material_views,
                        created_at = CURRENT_TIMESTAMP
                    """,
                    (
                        day_start.date().isoformat(),
                        int(row["active_users"] or 0),
                        int(row["total_events"] or 0),
                        int(row["menu_views"] or 0),
                        int(row["material_views"] or 0),
                    ),
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
