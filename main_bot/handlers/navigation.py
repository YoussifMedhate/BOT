import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import BaseFilter

from core.loader import get_menus, get_cached_materials, is_cached_custom_button
from core.keyboards import open_menu
from core.application.analytics_service import analytics_service

router = Router()


class MenuFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        return message.text in get_menus()


@router.message(F.text == "⬅️ Back")
async def handle_back(message: Message, state: FSMContext):
    data = await state.get_data()
    current_menu = data.get("current_menu", "main")
    menus = get_menus()
    parent = menus.get(current_menu, {}).get("parent")
    if parent:
        if await open_menu(message, state, parent):
            await analytics_service.track_menu_open(message, "main_bot", parent)
    else:
        if await open_menu(message, state, "main"):
            await analytics_service.track_menu_open(message, "main_bot", "main")



@router.message(MenuFilter())
async def handle_menu_navigation(message: Message, state: FSMContext):
    menu_name = message.text
    
    # Send materials if any exist
    materials = get_cached_materials(menu_name)
    if materials:
        async def send_material(mat) -> bool:
            try:
                if mat['channel_id'] == 'TEXT':
                    await message.bot.send_message(
                        chat_id=message.chat.id,
                        text=mat['description'],
                        parse_mode='HTML'
                    )
                else:
                    await message.bot.copy_message(
                        chat_id=message.chat.id,
                        from_chat_id=mat['channel_id'],
                        message_id=mat['message_id']
                    )
                return True
            except Exception as e:
                logging.warning(f"Failed to send material: {e}")
                return False

        for mat in materials:
            if await send_material(mat):
                await analytics_service.track_material_view(message, "main_bot", mat)


    # If the button is also a sub-menu, open it (show keyboard)
    menus = get_menus()
    if menu_name in menus:
        # Check if it has children menus (meaning it acts as a menu)
        # Actually in this bot, if it's in menus, it IS a menu, so we always open it.
        if await open_menu(message, state, menu_name):
            await analytics_service.track_menu_open(message, "main_bot", menu_name)

@router.message(F.text)
async def handle_unknown(message: Message, state: FSMContext):
    """أي رسالة نصية غير معروفة — يفتح القائمة الرئيسية."""
    if is_cached_custom_button(message.text):
        await message.answer("⏳ قريباً...\nهذا الزر قيد التطوير حالياً وسيتم توفيره في التحديثات القادمة.")
        return

    if await open_menu(message, state, "main"):
        await analytics_service.track_menu_open(message, "main_bot", "main")
