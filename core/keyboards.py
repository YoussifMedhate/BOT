import logging

from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from core.loader import get_menus


logger = logging.getLogger(__name__)


def build_keyboard(menu_data: dict) -> ReplyKeyboardMarkup:
    """Build a reply keyboard from a menu's buttons."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=btn) for btn in row]
            for row in menu_data["buttons"]
        ],
        resize_keyboard=True
    )

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Return a keyboard with a cancel button."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ إلغاء")]],
        resize_keyboard=True
    )


async def remove_reply_keyboard(message: Message):
    """Silently remove the reply keyboard."""
    msg = await message.answer("...", reply_markup=ReplyKeyboardRemove())
    try:
        await msg.delete()
    except Exception:
        pass


async def open_menu(
    message: Message,
    state: FSMContext,
    menu_name: str
) -> bool:
    """Open a menu and return whether it was available.

    A missing menu can happen after a fresh container deployment points at an
    empty database.  Handle it gracefully instead of allowing a KeyError to
    escape from a Telegram update handler.
    """
    menus = get_menus()
    menu_data = menus.get(menu_name)
    if menu_data is None:
        logger.error(
            "Requested menu is missing from the cache",
            extra={"event": "menu_missing", "menu_name": menu_name},
        )
        await message.answer(
            "⚠️ القائمة غير مهيأة حاليًا. تواصل مع مسؤول البوت لاستعادة قاعدة البيانات.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return False

    await state.update_data(current_menu=menu_name)
    buttons = menu_data.get("buttons") or []
    keyboard = build_keyboard(menu_data) if buttons else ReplyKeyboardRemove()
    await message.answer(
        menu_data["text"],
        reply_markup=keyboard
    )
    return True
