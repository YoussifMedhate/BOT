import asyncio
import logging

from core.platform_compat import configure_event_loop_policy
from run_admin import main as run_admin_bot
from run_main import main as run_main_bot
from run_dev import main as run_dev_bot
from core.bot import admin_bot
from core.runtime import shutdown_runtime, startup_runtime
from core.monitoring.logging_config import configure_logging
from admin_bot.backup_scheduler import start_backup_scheduler
from config.settings import BOT_ENV
from core.workers.health_monitor import start_health_monitor
from core.workers.snapshot_worker import start_snapshot_worker

configure_event_loop_policy()

async def start_all():
    configure_logging(BOT_ENV)
    await startup_runtime(admin_bot, configure_logs=False)

    try:
        results = await asyncio.gather(
            run_admin_bot(manage_runtime=False),
            run_main_bot(manage_runtime=False),
            run_dev_bot(manage_runtime=False),
            start_backup_scheduler(admin_bot),
            start_snapshot_worker(),
            start_health_monitor(),
            return_exceptions=True
        )
        for r in results:
            if isinstance(r, Exception):
                logging.error("Bot task crashed", extra={"event": "bot_task_crashed", "error": str(r)})
    finally:
        await shutdown_runtime()

if __name__ == "__main__":
    try:
        asyncio.run(start_all())
    except KeyboardInterrupt:
        logging.info("Bots are closed", extra={"event": "bots_closed"})
