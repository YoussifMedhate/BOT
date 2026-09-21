from aiogram import Router, F
from aiogram.types import Message

router = Router()

BOT_INFO_TEXT = """
.....
""".strip()


@router.message(F.text == "معلومات عن البوت")
async def show_bot_info(message: Message):
    """عرض معلومات تعريفية عن البوت."""
    await message.answer(BOT_INFO_TEXT, parse_mode="HTML")
