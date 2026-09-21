from core.loader import reload_menu, reload_menus
import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from menu_manager import (
    get_menu, get_children, list_menus, set_parent,
    update_text, delete_menu, duplicate_menu, MenuError,
)
from admin_bot.state import AdminState
from admin_bot.handlers.view_ops import format_menu_detail, _main_menu_keyboard
from core.keyboards import get_cancel_keyboard, remove_reply_keyboard
from core.database import db
from admin_bot.permissions import (
    DELETE_MENUS,
    DUPLICATE_MENU,
    EDIT_MENU_TEXT,
    MOVE_MENU,
    get_admin_scope,
    is_menu_in_scope,
    is_owner,
    require_callback_menu_scope,
    require_callback_permission,
    require_message_menu_scope,
    require_message_permission,
)

router = Router()



# ─── Delete Menu ─────────────────────────────────────────────

@router.callback_query(F.data == 'del')
async def cb_delete(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, DELETE_MENUS):
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    if not is_owner(callback.from_user.id) and menu_name == await get_admin_scope(callback.from_user.id):
        await callback.answer("❌ لا يمكنك حذف النود الأساسية المخصصة لك.", show_alert=True)
        return

    if menu_name.lower() in ['root', 'main', 'القائمة الرئيسية']:
        await callback.answer("❌ لا يمكنك حذف القائمة الرئيسية للبوت!", show_alert=True)
        return

    children = await get_children(menu_name)
    if children:
        await callback.answer("❌ لا يمكنك حذف هذه القائمة لأن بداخلها قوائم فرعية!\nقم بحذف القوائم الفرعية أولاً.", show_alert=True)
        return

    materials = await db.get_materials(menu_name)
    if materials:
        await callback.answer("❌ لا يمكنك حذف هذه القائمة لأن بداخلها ملفات أو رسائل!\nقم بحذف محتوياتها أولاً.", show_alert=True)
        return

    await callback.answer()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='نعم', callback_data='del_y'),
            InlineKeyboardButton(text='لا', callback_data=f'v:{menu_name}'),
        ]
    ])
    await callback.message.edit_text(
        f'هل أنت متأكد من حذف "{menu_name}"؟',
        reply_markup=keyboard,
    )


@router.callback_query(F.data == 'del_y')
async def cb_delete_yes(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, DELETE_MENUS):
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    if not is_owner(callback.from_user.id) and menu_name == await get_admin_scope(callback.from_user.id):
        await callback.answer("❌ لا يمكنك حذف النود الأساسية المخصصة لك.", show_alert=True)
        return
    try:
        menu_info = await get_menu(menu_name)
        parent = menu_info.get('parent')

        await delete_menu(menu_name, delete_children=True)
        await reload_menu(menu_name)
        if parent:
            await reload_menu(parent)
        await state.clear()

        # Go back to nav
        from admin_bot.handlers.view_ops import navigate_to_menu
        await callback.answer('✅ تم حذف القائمة', show_alert=True)
        if parent:
            await navigate_to_menu(callback, parent)
        else:
            await navigate_to_menu(callback, 'main')
            
    except MenuError as e:
        await callback.message.edit_text(f'❌ خطأ: {e}', reply_markup=_main_menu_keyboard())
        return
    except Exception as e:
        await state.clear()
        logging.exception(f"Unexpected error: {e}")
        await callback.message.edit_text('⚠️ حدث خطأ غير متوقع.', reply_markup=_main_menu_keyboard())
        return





# ─── Edit Text ───────────────────────────────────────────────

@router.callback_query(F.data == 'etxt')
async def cb_edit_text(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, EDIT_MENU_TEXT):
        return
    data = await state.get_data()
    if not await require_callback_menu_scope(callback, data.get('editing_menu')):
        return
    await callback.answer()
    await callback.message.answer('أدخل النص الجديد:', reply_markup=get_cancel_keyboard())
    await state.set_state(AdminState.waiting_edit_text)


@router.message(AdminState.waiting_edit_text)
async def on_edit_text(message: Message, state: FSMContext):
    if not await require_message_permission(message, EDIT_MENU_TEXT):
        await state.clear()
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_message_menu_scope(message, menu_name):
        await state.clear()
        return
    new_text = message.text

    await remove_reply_keyboard(message)

    try:
        await update_text(menu_name, new_text)
        await reload_menu(menu_name)
        await state.clear()
        await state.update_data(editing_menu=menu_name)

        detail_text, keyboard = await format_menu_detail(menu_name, message.from_user.id)
        await message.answer(f'✅ تم تغيير النص بنجاح!\n\n{detail_text}',
                             reply_markup=keyboard, parse_mode='HTML')
    except MenuError as e:
        await state.clear()
        await message.answer(f'❌ خطأ: {e}\nارجع للقائمة الرئيسية وابدأ من جديد.', reply_markup=_main_menu_keyboard())
        return
    except Exception as e:
        await state.clear()
        logging.exception(f"Unexpected error: {e}")
        await message.answer('⚠️ حدث خطأ غير متوقع.', reply_markup=_main_menu_keyboard())
        return


# ─── Change Parent ───────────────────────────────────────────

@router.callback_query(F.data == 'par')
async def cb_change_parent(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, MOVE_MENU):
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()

    # Get children to exclude them and self
    children = await get_children(menu_name)
    exclude = set(children) | {menu_name}

    menus = await list_menus()
    buttons = []
    for name in menus:
        if name not in exclude and await is_menu_in_scope(callback.from_user.id, name):
            buttons.append([InlineKeyboardButton(text=name, callback_data=f'chp:{name}')])
    if is_owner(callback.from_user.id):
        buttons.append([InlineKeyboardButton(text='بدون أب (root)', callback_data='chp:__none__')])
    buttons.append([InlineKeyboardButton(text='⬅️ إلغاء', callback_data=f'v:{menu_name}')])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text('اختر الأب الجديد:', reply_markup=keyboard)


@router.callback_query(F.data.startswith('chp:'))
async def cb_set_parent(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, MOVE_MENU):
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    parent_raw = callback.data.split(':', 1)[1]
    new_parent = None if parent_raw == '__none__' else parent_raw
    if new_parent is None and not is_owner(callback.from_user.id):
        await callback.answer("❌ لا يمكنك نقل القائمة خارج النطاق.", show_alert=True)
        return
    if new_parent and not await is_menu_in_scope(callback.from_user.id, new_parent):
        await callback.answer("❌ الأب الجديد خارج النطاق المسموح لك.", show_alert=True)
        return
    await callback.answer()

    try:
        await set_parent(menu_name, new_parent)
        await reload_menus()
        detail_text, keyboard = await format_menu_detail(menu_name, callback.from_user.id)
        await callback.message.edit_text(detail_text, reply_markup=keyboard, parse_mode='HTML')
    except MenuError as e:
        await callback.message.edit_text(f'❌ خطأ: {e}', reply_markup=_main_menu_keyboard())
        return
    except Exception as e:
        await state.clear()
        logging.exception(f"Unexpected error: {e}")
        await callback.message.edit_text('⚠️ حدث خطأ غير متوقع.', reply_markup=_main_menu_keyboard())
        return


# ─── Duplicate Menu ──────────────────────────────────────────

@router.callback_query(F.data == 'dup')
async def cb_duplicate(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, DUPLICATE_MENU):
        return
    data = await state.get_data()
    if not await require_callback_menu_scope(callback, data.get('editing_menu')):
        return
    await callback.answer()
    await callback.message.answer('أدخل اسم النسخة:', reply_markup=get_cancel_keyboard())
    await state.set_state(AdminState.waiting_dup_name)


@router.message(AdminState.waiting_dup_name)
async def on_dup_name(message: Message, state: FSMContext):
    if not await require_message_permission(message, DUPLICATE_MENU):
        await state.clear()
        return
    data = await state.get_data()
    old_name = data.get('editing_menu')
    if not await require_message_menu_scope(message, old_name):
        await state.clear()
        return
    new_name = message.text

    await remove_reply_keyboard(message)

    try:
        await duplicate_menu(old_name, new_name)
        await reload_menus()
        await state.clear()
        await state.update_data(editing_menu=new_name)

        detail_text, keyboard = await format_menu_detail(new_name, message.from_user.id)
        await message.answer(f'✅ تم نسخ القائمة بنجاح!\n\n{detail_text}',
                             reply_markup=keyboard, parse_mode='HTML')
    except MenuError as e:
        await state.clear()
        await message.answer(f'❌ خطأ: {e}', reply_markup=_main_menu_keyboard())
        return
    except Exception as e:
        await state.clear()
        logging.exception(f"Unexpected error: {e}")
        await message.answer('⚠️ حدث خطأ غير متوقع.', reply_markup=_main_menu_keyboard())
        return
