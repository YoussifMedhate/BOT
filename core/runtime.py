from __future__ import annotations

import logging

from aiogram import Bot

from config.settings import BOT_ENV
from core.application.analytics_service import analytics_service
from core.bot import close_bots
from core.database import db
from core.loader import get_menus, reload_menus
from core.monitoring.alerts import alert_manager
from core.monitoring.logging_config import configure_logging

logger = logging.getLogger(__name__)


async def startup_runtime(alert_bot: Bot | None = None, configure_logs: bool = True) -> None:
    if configure_logs:
        configure_logging(BOT_ENV)
    if alert_bot is not None:
        alert_manager.bind_bot(alert_bot)
    await db.init_db()
    await reload_menus()
    if "main" not in get_menus():
        raise RuntimeError(
            "Database initialization completed without the required 'main' menu. "
            "Restore the database or check DB_PATH."
        )
    await analytics_service.start()
    logger.info("Runtime ready", extra={"event": "runtime_ready", "env": BOT_ENV})


async def shutdown_runtime(close_bot_sessions: bool = True) -> None:
    try:
        await analytics_service.stop()
    finally:
        if close_bot_sessions:
            await close_bots()
        await db.close()
        logger.info("Runtime stopped", extra={"event": "runtime_stopped"})
