from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Dict, Any, Awaitable
from config.settings import DEV_IDS


class DevAuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if event.from_user.id not in DEV_IDS:
            return
        return await handler(event, data)
