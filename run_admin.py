import asyncio
import contextlib

from core.platform_compat import configure_event_loop_policy
from core.bot import admin_bot
from core.runtime import shutdown_runtime, startup_runtime
from admin_bot.app import dp
from admin_bot.backup_scheduler import start_backup_scheduler
from core.workers.health_monitor import start_health_monitor
from core.workers.snapshot_worker import start_snapshot_worker

configure_event_loop_policy()

async def main(manage_runtime: bool = True):
    background_tasks: list[asyncio.Task] = []
    if manage_runtime:
        await startup_runtime(admin_bot)
        background_tasks.append(asyncio.create_task(start_backup_scheduler(admin_bot)))
        background_tasks.append(asyncio.create_task(start_snapshot_worker()))
        background_tasks.append(asyncio.create_task(start_health_monitor()))
    try:
        await admin_bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(admin_bot, allowed_updates=["message", "callback_query"])
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if manage_runtime:
            await shutdown_runtime()


if __name__ == '__main__':
    asyncio.run(main())
