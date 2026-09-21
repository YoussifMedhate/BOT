from aiogram import Dispatcher
from dev_bot.handlers.start import router as start_router
from dev_bot.middlewares.auth import DevAuthMiddleware
from core.analytics.middleware import AnalyticsMiddleware
from core.monitoring.rate_limit import RateLimitMiddleware

dp = Dispatcher()
dp.message.middleware(DevAuthMiddleware())
dp.callback_query.middleware(DevAuthMiddleware())
dp.message.middleware(RateLimitMiddleware())
dp.callback_query.middleware(RateLimitMiddleware())
dp.message.middleware(AnalyticsMiddleware("dev_bot"))
dp.callback_query.middleware(AnalyticsMiddleware("dev_bot"))
dp.include_router(start_router)
