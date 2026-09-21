from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from admin_bot.permissions import get_admin_permissions, is_allowed_admin, is_owner


class AdminMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user and not await is_allowed_admin(user.id):
            if isinstance(event, Message):
                await event.answer('غير مصرح لك باستخدام هذا البوت')
            elif isinstance(event, CallbackQuery):
                await event.answer(' غير مصرح', show_alert=True)
            return
        if user:
            data["admin_is_owner"] = is_owner(user.id)
            data["admin_permissions"] = await get_admin_permissions(user.id)
        return await handler(event, data)
