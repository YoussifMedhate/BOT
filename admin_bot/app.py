from aiogram import Dispatcher
from admin_bot.middleware import AdminMiddleware
from core.analytics.middleware import AnalyticsMiddleware
from core.monitoring.rate_limit import RateLimitMiddleware
from admin_bot.handlers.start import router as start_router
from admin_bot.handlers.view_ops import router as view_router
from admin_bot.handlers.menu_ops import router as menu_router
from admin_bot.handlers.button_ops import router as button_router
from admin_bot.handlers.material_ops import router as material_router
from admin_bot.handlers.backup_ops import router as backup_router
from admin_bot.handlers.analytics_ops import router as analytics_router
from admin_bot.handlers.admin_ops import router as admin_router
from admin_bot.handlers.fallback import router as fallback_router

dp = Dispatcher()

# Apply admin-only middleware
dp.message.middleware(AdminMiddleware())
dp.callback_query.middleware(AdminMiddleware())
dp.message.middleware(RateLimitMiddleware())
dp.callback_query.middleware(RateLimitMiddleware())
dp.message.middleware(AnalyticsMiddleware("admin_bot"))
dp.callback_query.middleware(AnalyticsMiddleware("admin_bot"))

# Include all routers — fallback MUST be last
dp.include_router(start_router)
dp.include_router(view_router)
dp.include_router(menu_router)
dp.include_router(button_router)
dp.include_router(material_router)
dp.include_router(backup_router)
dp.include_router(analytics_router)
dp.include_router(admin_router)
dp.include_router(fallback_router)
