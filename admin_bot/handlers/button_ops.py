from core.loader import reload_custom_buttons, reload_menu, reload_menus
import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from menu_manager import (
    get_menu, get_children, add_menu, add_button,
    remove_button, delete_menu, swap_buttons, MenuError,
)
from admin_bot.state import AdminState
from admin_bot.handlers.view_ops import format_menu_detail, _main_menu_keyboard
from core.keyboards import get_cancel_keyboard, remove_reply_keyboard
from admin_bot.permissions import (
    ADD_BUTTONS,
    DELETE_BUTTONS,
    REORDER_BUTTONS,
    require_callback_menu_scope,
    require_callback_permission,
    require_message_menu_scope,
    require_message_permission,
)

router = Router()


async def _get_menu_buttons(menu_name: str) -> list[str]:
    """Get all button texts from a menu, excluding Back buttons."""
    menu = await get_menu(menu_name)
    buttons = menu.get('buttons', [])
    result = []
    for row in buttons:
        for btn in row:
            if btn != '⬅️ Back':
                result.append(btn)
    return result


def _find_button_position(menu: dict, button_text: str) -> tuple[int | None, int | None]:
    """Return the row and position for a button inside a menu payload."""
    for row_index, row in enumerate(menu.get("buttons", [])):
        for position_index, text in enumerate(row):
            if text == button_text:
                return row_index, position_index
    return None, None


# ─── Add Button ──────────────────────────────────────────────

@router.callback_query(F.data == 'badd')
async def cb_add_button(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, ADD_BUTTONS):
        return
    data = await state.get_data()
    if not await require_callback_menu_scope(callback, data.get('editing_menu')):
        return
    await callback.answer()
    await callback.message.answer('أدخل نص الزر الجديد:', reply_markup=get_cancel_keyboard())
    await state.set_state(AdminState.waiting_btn_text)


@router.message(AdminState.waiting_btn_text)
async def on_btn_text(message: Message, state: FSMContext):
    if not await require_message_permission(message, ADD_BUTTONS):
        await state.clear()
        return
    data = await state.get_data()
    if not await require_message_menu_scope(message, data.get('editing_menu')):
        await state.clear()
        return
    await state.update_data(new_btn_text=message.text)
    await message.answer('🔢 ممتاز! الآن أدخل **رقم الصف** الذي تريد وضع الزر فيه (يبدأ من 0):\n*(مثال: أرسل 0 للصف الأول، أو 1 للصف الثاني، أو رقم صف موجود لوضع الزر بجواره)*', reply_markup=get_cancel_keyboard())
    await state.set_state(AdminState.waiting_btn_row)

@router.message(AdminState.waiting_btn_row)
async def on_btn_row(message: Message, state: FSMContext):
    if not await require_message_permission(message, ADD_BUTTONS):
        await state.clear()
        return
    data = await state.get_data()
    if not await require_message_menu_scope(message, data.get('editing_menu')):
        await state.clear()
        return
    if not message.text.isdigit():
        await message.answer("❌ رجاءً أدخل رقماً صحيحاً (مثال: 0 أو 1):")
        return

    row_index = int(message.text)
    await state.update_data(new_btn_row=row_index)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📁 قائمة فرعية", callback_data="btn_type_submenu"),
            InlineKeyboardButton(text="⚙️ وظيفة مخصصة", callback_data="btn_type_custom"),
        ]
    ])
    await message.answer('ماذا تريد أن يفعل هذا الزر عند الضغط عليه؟', reply_markup=keyboard)
    await state.set_state(AdminState.waiting_btn_type)

@router.callback_query(F.data == "btn_type_submenu", AdminState.waiting_btn_type)
async def cb_btn_type_submenu(callback: CallbackQuery, state: FSMContext):
    from core.database import db

    if not await require_callback_permission(callback, ADD_BUTTONS):
        return
    
    data = await state.get_data()
    parent = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, parent):
        return
    await callback.answer()
    button_text = data.get('new_btn_text')
    row_index = data.get('new_btn_row')

    menu_name = button_text  # استخدام النص العربي نفسه كأيدي للقائمة

    await remove_reply_keyboard(callback.message)

    if await db.menu_exists(menu_name):
        await callback.message.answer("❌ قائمة بهذا الاسم موجودة بالفعل! الرجاء اختيار اسم آخر.")
        await state.clear()
        return

    try:
        await add_menu(menu_name, parent=parent, text=button_text, row=row_index)
        await reload_menus()
        await state.clear()
        await state.update_data(editing_menu=parent)

        detail_text, keyboard = await format_menu_detail(parent, callback.from_user.id)
        await callback.message.edit_text(f'✅ تم إنشاء القائمة الفرعية بنجاح!\n\n{detail_text}',
                             reply_markup=keyboard, parse_mode='HTML')
    except MenuError as e:
        await state.clear()
        await callback.message.edit_text(f'❌ خطأ: {e}', reply_markup=_main_menu_keyboard())
    except Exception as e:
        await state.clear()
        logging.exception(f"Unexpected error: {e}")
        await callback.message.edit_text('⚠️ حدث خطأ غير متوقع.', reply_markup=_main_menu_keyboard())

@router.callback_query(F.data == "btn_type_custom", AdminState.waiting_btn_type)
async def cb_btn_type_custom(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, ADD_BUTTONS):
        return
    data = await state.get_data()
    if not await require_callback_menu_scope(callback, data.get('editing_menu')):
        return
    await callback.answer()
    await callback.message.answer("يرجى كتابة وصف دقيق للوظيفة التي سيقوم بها هذا الزر لكي يقوم المبرمج بتنفيذها:", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminState.waiting_btn_custom_desc)

@router.message(AdminState.waiting_btn_custom_desc)
async def on_btn_custom_desc(message: Message, state: FSMContext):
    if not await require_message_permission(message, ADD_BUTTONS):
        await state.clear()
        return
    desc = message.text.strip()
    data = await state.get_data()
    parent = data.get('editing_menu')
    if not await require_message_menu_scope(message, parent):
        await state.clear()
        return
    button_text = data.get('new_btn_text')
    row_index = data.get('new_btn_row')

    await remove_reply_keyboard(message)

    try:
        from core.database import db
        updated_menu = await add_button(parent, button_text, row=row_index)
        saved_row, saved_position = _find_button_position(updated_menu, button_text)
        await db.add_custom_button(
            button_text,
            desc,
            menu_name=parent,
            row_index=saved_row,
            position_index=saved_position,
        )
        
        from core.bot import main_bot
        from config.settings import DEV_CHANNEL_ID
        
        alert_text = (
            f"🚨 طلب برمجة زر جديد 🚨\n"
            f"اسم الزر: {button_text}\n"
            f"القائمة الأب: {parent}\n"
            f"الوصف/المطلوب: {desc}\n"
            f"الحالة: بانتظار البرمجة"
        )
        try:
            await main_bot.send_message(chat_id=DEV_CHANNEL_ID, text=alert_text)
        except Exception as e:
            logging.error(f"Could not send to dev channel: {e}")
            await message.answer(f"⚠️ تنبيه: تم حفظ الزر ولكن تعذر الإرسال لقناة المطورين. تأكد من إعداد القناة والبوت. الخطأ: {e}")

        await reload_menu(parent)
        await reload_custom_buttons()
        await state.clear()
        await state.update_data(editing_menu=parent)

        detail_text, keyboard = await format_menu_detail(parent, message.from_user.id)
        await message.answer(f'✅ تم إضافة الزر وتسجيل الطلب بنجاح!\n\n{detail_text}',
                             reply_markup=keyboard, parse_mode='HTML')
    except MenuError as e:
        await state.clear()
        await message.answer(f'❌ خطأ: {e}', reply_markup=_main_menu_keyboard())
    except Exception as e:
        await state.clear()
        logging.exception(f"Unexpected error: {e}")
        await message.answer('⚠️ حدث خطأ غير متوقع.', reply_markup=_main_menu_keyboard())


# ─── Remove Button ───────────────────────────────────────────

@router.callback_query(F.data == 'brem')
async def cb_remove_button(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, DELETE_BUTTONS):
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()

    btn_texts = await _get_menu_buttons(menu_name)
    if not btn_texts:
        await callback.message.answer('لا توجد أزرار لحذفها.')
        return

    buttons = []
    for btn in btn_texts:
        buttons.append([InlineKeyboardButton(text=btn, callback_data=f'brm:{btn}')])
    buttons.append([InlineKeyboardButton(text='⬅️ إلغاء', callback_data=f'v:{menu_name}')])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text('اختر الزر المراد حذفه:', reply_markup=keyboard)


@router.callback_query(F.data.startswith('brm:'))
async def cb_remove_btn_confirm(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, DELETE_BUTTONS):
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    button_text = callback.data.split(':', 1)[1]

    from core.database import db
    if await db.menu_exists(button_text):
        children = await get_children(button_text)
        if children:
            await callback.answer("❌ لا يمكنك حذف هذا الزر لأنه قائمة تحتوي على قوائم فرعية!\nقم بحذف القوائم الفرعية أولاً.", show_alert=True)
            return

        materials = await db.get_materials(button_text)
        if materials:
            await callback.answer("❌ لا يمكنك حذف هذا الزر لأنه قائمة تحتوي على ملفات أو رسائل!\nقم بحذف محتوياتها أولاً.", show_alert=True)
            return

    await callback.answer()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='نعم', callback_data=f'bdel_y:{button_text}'),
            InlineKeyboardButton(text='لا', callback_data=f'v:{menu_name}'),
        ]
    ])
    await callback.message.edit_text(
        f'هل أنت متأكد من حذف زر "{button_text}"؟',
        reply_markup=keyboard,
    )

@router.callback_query(F.data.startswith('bdel_y:'))
async def cb_remove_btn_yes(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, DELETE_BUTTONS):
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    button_text = callback.data.split(':', 1)[1]
    await callback.answer()

    try:
        from core.database import db
        removes_menu = await db.menu_exists(button_text)
        if removes_menu:
            await delete_menu(button_text, delete_children=True)
        else:
            await remove_button(menu_name, button_text)
            await db.delete_custom_button(button_text)
            
        if removes_menu:
            await reload_menus()
        else:
            await reload_menu(menu_name)
            await reload_custom_buttons()
        detail_text, keyboard = await format_menu_detail(menu_name, callback.from_user.id)
        await callback.message.edit_text(
            f'✅ تم حذف الزر بنجاح!\n\n{detail_text}',
            reply_markup=keyboard,
            parse_mode='HTML',
        )
    except MenuError as e:
        await callback.message.edit_text(f'❌ خطأ: {e}', reply_markup=_main_menu_keyboard())
        return
    except Exception as e:
        await state.clear()
        logging.exception(f"Unexpected error: {e}")
        await callback.message.edit_text('⚠️ حدث خطأ غير متوقع.', reply_markup=_main_menu_keyboard())
        return


# ─── Swap Buttons ────────────────────────────────────────────

@router.callback_query(F.data == 'bswap')
async def cb_swap_buttons(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, REORDER_BUTTONS):
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()

    btn_texts = await _get_menu_buttons(menu_name)
    if len(btn_texts) < 2:
        await callback.message.answer('يجب وجود زرارين على الأقل للتبديل.')
        return

    buttons = []
    for btn in btn_texts:
        buttons.append([InlineKeyboardButton(text=btn, callback_data=f'bs1:{btn}')])
    buttons.append([InlineKeyboardButton(text='⬅️ إلغاء', callback_data=f'v:{menu_name}')])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text('اختار الزر الأول:', reply_markup=keyboard)


@router.callback_query(F.data.startswith('bs1:'))
async def cb_swap_first(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, REORDER_BUTTONS):
        return
    first_btn = callback.data.split(':', 1)[1]
    await state.update_data(swap_first=first_btn)

    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()

    btn_texts = await _get_menu_buttons(menu_name)
    buttons = []
    for btn in btn_texts:
        if btn != first_btn:
            buttons.append([InlineKeyboardButton(text=btn, callback_data=f'bs2:{btn}')])
    buttons.append([InlineKeyboardButton(text='⬅️ إلغاء', callback_data=f'v:{menu_name}')])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text('اختار الزر الثاني:', reply_markup=keyboard)


@router.callback_query(F.data.startswith('bs2:'))
async def cb_swap_second(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, REORDER_BUTTONS):
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    first_btn = data.get('swap_first')
    second_btn = callback.data.split(':', 1)[1]
    await callback.answer()

    try:
        await swap_buttons(menu_name, first_btn, second_btn)
        await reload_menu(menu_name)
        detail_text, keyboard = await format_menu_detail(menu_name, callback.from_user.id)
        await callback.message.edit_text(
            f'✅ تم تبديل الزرارين بنجاح!\n\n{detail_text}',
            reply_markup=keyboard,
            parse_mode='HTML',
        )
    except MenuError as e:
        await callback.message.edit_text(f'❌ خطأ: {e}', reply_markup=_main_menu_keyboard())
        return
    except Exception as e:
        await state.clear()
        logging.exception(f"Unexpected error: {e}")
        await callback.message.edit_text('⚠️ حدث خطأ غير متوقع.', reply_markup=_main_menu_keyboard())
        return
