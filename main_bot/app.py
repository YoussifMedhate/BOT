from aiogram import Dispatcher

from main_bot.handlers.start import router as start_router
from main_bot.handlers.bot_info import router as bot_info_router
from main_bot.handlers.navigation import router as navigation_router
from core.analytics.middleware import AnalyticsMiddleware
from core.monitoring.rate_limit import RateLimitMiddleware


dp = Dispatcher()

dp.message.middleware(RateLimitMiddleware())
dp.callback_query.middleware(RateLimitMiddleware())
dp.message.middleware(AnalyticsMiddleware("main_bot"))
dp.callback_query.middleware(AnalyticsMiddleware("main_bot"))

dp.include_router(start_router)
dp.include_router(bot_info_router)   # قبل navigation عشان يمسك الزر أولاً
dp.include_router(navigation_router)
