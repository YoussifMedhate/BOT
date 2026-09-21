import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from menu_manager import get_menu, get_tree, MenuError
from core.database import db
from admin_bot.permissions import (
    ADD_BUTTONS,
    DELETE_BUTTONS,
    DELETE_MENUS,
    DUPLICATE_MENU,
    EDIT_MENU_TEXT,
    MATERIAL_PERMISSIONS,
    MENU_AREA_PERMISSIONS,
    MOVE_MENU,
    REORDER_BUTTONS,
    get_admin_scope,
    has_any_permission,
    has_permission,
    is_menu_in_scope,
    require_callback_menu_scope,
)

router = Router()


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    """Keyboard with a single button back to the main admin menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏠 القائمة الرئيسية', callback_data='list')]
    ])


async def format_menu_detail(name: str, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Format menu details and action keyboard. Returns (text, keyboard)."""
    menu = await get_menu(name)
    parent = menu.get('parent', '—') or '—'
    text = menu.get('text', '—') or '—'
    buttons = menu.get('buttons', [])

    # Build buttons display
    buttons_display = ''
    if buttons:
        for i, row in enumerate(buttons):
            row_buttons = ' | '.join(row)
            buttons_display += f'  صف {i}: [ {row_buttons} ]\n'
    else:
        buttons_display = '  (لا توجد أزرار)\n'

    detail_text = (
        f'📂 <b>القائمة:</b> {name}\n'
        f'👆 <b>الأب:</b> {parent}\n'
        f'📝 <b>النص:</b> {text}\n'
        f'🔘 <b>الأزرار:</b>\n{buttons_display}'
    )

    rows = []
    if await has_permission(user_id, EDIT_MENU_TEXT):
        rows.append([InlineKeyboardButton(text='📝 تغيير النص', callback_data='etxt')])

    parent_row = []
    if await has_permission(user_id, MOVE_MENU):
        parent_row.append(InlineKeyboardButton(text='🔄 تغيير الأب', callback_data='par'))
    if await has_permission(user_id, DUPLICATE_MENU):
        parent_row.append(InlineKeyboardButton(text='📄 نسخ', callback_data='dup'))
    if parent_row:
        rows.append(parent_row)

    button_row = []
    if await has_permission(user_id, ADD_BUTTONS):
        button_row.append(InlineKeyboardButton(text='➕ إضافة زر', callback_data='badd'))
    if await has_permission(user_id, DELETE_BUTTONS):
        button_row.append(InlineKeyboardButton(text='❌ حذف زر', callback_data='brem'))
    if button_row:
        rows.append(button_row)

    order_row = []
    if await has_permission(user_id, REORDER_BUTTONS):
        order_row.append(InlineKeyboardButton(text='🔀 تبديل زرارين', callback_data='bswap'))
    if await has_any_permission(user_id, MATERIAL_PERMISSIONS):
        order_row.append(
            InlineKeyboardButton(
                text=f'📎 الملفات ({await db.count_materials(name)})',
                callback_data=f'mat:{name}',
            )
        )
    if order_row:
        rows.append(order_row)

    if await has_permission(user_id, DELETE_MENUS):
        rows.append([InlineKeyboardButton(text='🗑 حذف القائمة', callback_data='del')])

    root_menu = await get_admin_scope(user_id)
    can_go_parent = parent != '—' and parent and await is_menu_in_scope(user_id, parent)
    back_callback = f'nav:{parent}' if can_go_parent and name != root_menu else 'panel'
    rows.append([InlineKeyboardButton(text='⬅️ رجوع', callback_data=back_callback)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

    return detail_text, keyboard


@router.callback_query(F.data == 'list')
async def cb_list(callback: CallbackQuery):
    if not await has_any_permission(callback.from_user.id, MENU_AREA_PERMISSIONS):
        await callback.answer("❌ لا تملك صلاحية عرض القوائم.", show_alert=True)
        return
    await callback.answer()
    await navigate_to_menu(callback, await get_admin_scope(callback.from_user.id))


async def navigate_to_menu(callback: CallbackQuery, menu_name: str, state: FSMContext = None):
    if not await require_callback_menu_scope(callback, menu_name):
        return
    try:
        menu = await get_menu(menu_name)
    except MenuError:
        await callback.answer("هذا الزر ليس قائمة بحد ذاته. يمكنك الدخول لقائمة التعديل لإضافته كقائمة.", show_alert=True)
        await callback.message.edit_text(
            '❌ القائمة غير موجودة أو غير متاحة.',
            reply_markup=_main_menu_keyboard()
        )
        return

    # Check if menu has actual child buttons (excluding Back button)
    buttons = menu.get('buttons', [])
    has_children = any(
        btn for row in buttons for btn in row if btn != "⬅️ Back"
    )

    # If no children, go directly to edit view
    if not has_children:
        if state:
            await state.update_data(editing_menu=menu_name)
        detail_text, keyboard = await format_menu_detail(menu_name, callback.from_user.id)
        await callback.message.edit_text(detail_text, reply_markup=keyboard, parse_mode='HTML')
        return

    text = (
        f"📂 <b>القائمة الحالية:</b> {menu_name}\n"
        f"📝 <b>النص المعروض :</b> {menu.get('text', '—')}\n\n"
        f"👇 يمكنك تعديل هذه القائمة أو الدخول للقوائم الفرعية:"
    )

    keyboard_buttons = []

    # 1. Edit button at the top
    keyboard_buttons.append([InlineKeyboardButton(text="⚙️ تعديل هذه القائمة", callback_data=f"v:{menu_name}")])

    # 2. Child buttons
    for row in buttons:
        kb_row = []
        for btn in row:
            if btn == "⬅️ Back":
                continue
            if not await db.menu_exists(btn):
                continue
            if not await is_menu_in_scope(callback.from_user.id, btn):
                continue
            callback_data = f"nav:{btn}"
            if len(callback_data.encode('utf-8')) > 64:
                logging.warning(f"Button '{btn}' callback_data exceeds 64 bytes, skipping")
                continue
            kb_row.append(InlineKeyboardButton(text=btn, callback_data=callback_data))
        if kb_row:
            keyboard_buttons.append(kb_row)

    # 3. Back button at the bottom
    parent = menu.get('parent')
    root_menu = await get_admin_scope(callback.from_user.id)
    if parent and menu_name != root_menu and await is_menu_in_scope(callback.from_user.id, parent):
        keyboard_buttons.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data=f"nav:{parent}")])
    else:
        keyboard_buttons.append([InlineKeyboardButton(text="⬅️ لوحة التحكم", callback_data="panel")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')


@router.callback_query(F.data.startswith('nav:'))
async def cb_nav(callback: CallbackQuery, state: FSMContext):
    if not await has_any_permission(callback.from_user.id, MENU_AREA_PERMISSIONS):
        await callback.answer("❌ لا تملك صلاحية عرض القوائم.", show_alert=True)
        return
    menu_name = callback.data.split(':', 1)[1]
    await navigate_to_menu(callback, menu_name, state=state)


@router.callback_query(F.data == 'tree')
async def cb_tree(callback: CallbackQuery):
    if not await has_any_permission(callback.from_user.id, MENU_AREA_PERMISSIONS):
        await callback.answer("❌ لا تملك صلاحية عرض الشجرة.", show_alert=True)
        return
    await callback.answer()
    tree_str = await get_tree(await get_admin_scope(callback.from_user.id))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬅️ رجوع', callback_data='panel')]
    ])
    await callback.message.edit_text(
        f'🌳 <b>شجرة القوائم:</b>\n<pre>{tree_str}</pre>',
        reply_markup=keyboard,
        parse_mode='HTML',
    )


@router.callback_query(F.data.startswith('v:'))
async def cb_view_menu(callback: CallbackQuery, state: FSMContext):
    menu_name = callback.data.split(':', 1)[1]
    if not await has_any_permission(callback.from_user.id, MENU_AREA_PERMISSIONS):
        await callback.answer("❌ لا تملك صلاحية عرض القوائم.", show_alert=True)
        return
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()
    await state.update_data(editing_menu=menu_name)

    try:
        detail_text, keyboard = await format_menu_detail(menu_name, callback.from_user.id)
        await callback.message.edit_text(detail_text, reply_markup=keyboard, parse_mode='HTML')
    except MenuError as e:
        await callback.message.edit_text(f'❌ خطأ: {e}', reply_markup=_main_menu_keyboard())
        return
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        await callback.message.edit_text('⚠️ حدث خطأ غير متوقع.', reply_markup=_main_menu_keyboard())
        return
