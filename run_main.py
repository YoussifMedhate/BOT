import asyncio

from core.platform_compat import configure_event_loop_policy
from core.bot import admin_bot, main_bot
from core.runtime import shutdown_runtime, startup_runtime
from main_bot.app import dp

configure_event_loop_policy()

async def main(manage_runtime: bool = True):
    if manage_runtime:
        await startup_runtime(admin_bot)
    try:
        await main_bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(main_bot, allowed_updates=["message", "callback_query"])
    finally:
        if manage_runtime:
            await shutdown_runtime()


if __name__ == "__main__":
    asyncio.run(main())
