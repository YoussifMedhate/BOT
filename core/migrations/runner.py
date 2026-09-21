from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: Sequence[str]
    down: Sequence[str]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="analytics_core",
        up=(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                chat_id INTEGER,
                message_id INTEGER,
                menu_name TEXT,
                material_id INTEGER,
                payload TEXT NOT NULL DEFAULT '{}',
                occurred_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                event_count INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS analytics_material_stats (
                material_id INTEGER PRIMARY KEY,
                menu_name TEXT,
                view_count INTEGER NOT NULL DEFAULT 0,
                last_viewed_at TEXT,
                FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS analytics_daily_snapshots (
                day TEXT PRIMARY KEY,
                active_users INTEGER NOT NULL DEFAULT 0,
                total_events INTEGER NOT NULL DEFAULT 0,
                menu_views INTEGER NOT NULL DEFAULT 0,
                material_views INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_analytics_events_time ON analytics_events(occurred_at)",
            "CREATE INDEX IF NOT EXISTS idx_analytics_events_type_time ON analytics_events(event_type, occurred_at)",
            "CREATE INDEX IF NOT EXISTS idx_analytics_events_user_time ON analytics_events(user_id, occurred_at)",
            "CREATE INDEX IF NOT EXISTS idx_analytics_events_menu ON analytics_events(menu_name)",
            "CREATE INDEX IF NOT EXISTS idx_user_sessions_last_seen ON user_sessions(last_seen_at)",
            "CREATE INDEX IF NOT EXISTS idx_material_stats_views ON analytics_material_stats(view_count DESC)",
        ),
        down=(
            "DROP INDEX IF EXISTS idx_material_stats_views",
            "DROP INDEX IF EXISTS idx_user_sessions_last_seen",
            "DROP INDEX IF EXISTS idx_analytics_events_menu",
            "DROP INDEX IF EXISTS idx_analytics_events_user_time",
            "DROP INDEX IF EXISTS idx_analytics_events_type_time",
            "DROP INDEX IF EXISTS idx_analytics_events_time",
            "DROP TABLE IF EXISTS analytics_daily_snapshots",
            "DROP TABLE IF EXISTS analytics_material_stats",
            "DROP TABLE IF EXISTS user_sessions",
            "DROP TABLE IF EXISTS analytics_events",
        ),
    ),
)


async def ensure_migration_table(conn: Any) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """)


async def get_applied_versions(conn: Any) -> set[int]:
    await ensure_migration_table(conn)
    async with conn.execute("SELECT version FROM schema_migrations") as cursor:
        rows = await cursor.fetchall()
    return {int(row[0]) for row in rows}


async def apply_migrations(conn: Any) -> list[int]:
    applied_versions = await get_applied_versions(conn)
    applied_now: list[int] = []

    for migration in MIGRATIONS:
        if migration.version in applied_versions:
            continue

        try:
            for statement in migration.up:
                await conn.execute(statement)
            await conn.execute(
                """
                INSERT INTO schema_migrations (version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await conn.commit()
            applied_now.append(migration.version)
        except Exception:
            await conn.rollback()
            raise

    return applied_now


async def rollback_migration(conn: Any, version: int) -> None:
    migration = next((item for item in MIGRATIONS if item.version == version), None)
    if migration is None:
        raise ValueError(f"Unknown migration version: {version}")

    applied_versions = await get_applied_versions(conn)
    if version not in applied_versions:
        return

    try:
        for statement in migration.down:
            await conn.execute(statement)
        await conn.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
