from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import default_state
from aiogram.types import Message

from admin_bot.handlers.start import get_panel_keyboard

router = Router()


@router.message(StateFilter(default_state))
async def catch_all(message: Message, state: FSMContext):
    """أي رسالة خارج أي state معروف — يعود للقائمة الرئيسية."""
    await message.answer(
        '🏠 القائمة الرئيسية:',
        reply_markup=await get_panel_keyboard(message.from_user.id),
    )
