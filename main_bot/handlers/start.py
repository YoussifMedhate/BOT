from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from core.keyboards import open_menu
from core.database import db
from core.application.analytics_service import analytics_service

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or "بدون يوزر"
    full_name = message.from_user.full_name
    
    await db.add_user(user_id=user_id, username=username, full_name=full_name)
    
    if await open_menu(message, state, "main"):
        await analytics_service.track_menu_open(message, "main_bot", "main")
