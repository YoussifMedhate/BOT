from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from admin_bot.permissions import (
    ALL_PERMISSION_CODES,
    PERMISSION_BY_CODE,
    PERMISSIONS,
    VIEW_MENUS,
    deny_callback,
    deny_message,
    is_owner,
)
from admin_bot.state import AdminManageStates
from core.database import db
from core.keyboards import get_cancel_keyboard, remove_reply_keyboard

router = Router()


def _admins_keyboard(admins: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ إضافة مشرف", callback_data="adm_add")]]
    for admin in admins:
        status = "✅" if admin["is_active"] else "⛔"
        name = admin.get("name") or str(admin["user_id"])
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{status} {name}",
                    callback_data=f"adm:{admin['user_id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _permission_label(permission: str, enabled: bool) -> str:
    marker = "✅" if enabled else "▫️"
    return f"{marker} {PERMISSION_BY_CODE[permission].label}"


def _admin_detail_keyboard(admin: dict) -> InlineKeyboardMarkup:
    user_id = admin["user_id"]
    enabled = set(admin.get("permissions", []))
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="✅ تفعيل الكل", callback_data=f"adm_all:{user_id}"),
            InlineKeyboardButton(text="▫️ إلغاء الكل", callback_data=f"adm_none:{user_id}"),
        ]
    ]

    for index in range(0, len(PERMISSIONS), 2):
        row = []
        for permission in PERMISSIONS[index:index + 2]:
            row.append(
                InlineKeyboardButton(
                    text=_permission_label(permission.code, permission.code in enabled),
                    callback_data=f"adm_perm:{user_id}:{permission.code}",
                )
            )
        rows.append(row)

    active_text = "⛔ إيقاف المشرف" if admin["is_active"] else "✅ تفعيل المشرف"
    rows.extend(
        [
            [InlineKeyboardButton(text="📍 تغيير النود", callback_data=f"adm_scope:{user_id}")],
            [InlineKeyboardButton(text=active_text, callback_data=f"adm_active:{user_id}")],
            [InlineKeyboardButton(text="🗑 حذف المشرف", callback_data=f"adm_del:{user_id}")],
            [InlineKeyboardButton(text="⬅️ رجوع", callback_data="admins")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_scope_picker(message: Message, state: FSMContext, menu_name: str = "main") -> None:
    data = await state.get_data()
    user_id = data.get("target_admin_id")
    if not user_id:
        await message.edit_text("❌ انتهت الجلسة. افتح إدارة المشرفين مرة أخرى.")
        return

    admin = await db.get_admin_user(int(user_id))
    if not admin:
        await message.edit_text("❌ المشرف غير موجود.", reply_markup=_admins_keyboard(await db.list_admin_users()))
        return

    menu = await db.get_menu(menu_name)
    if not menu:
        await message.edit_text("❌ القائمة غير موجودة أو تم حذفها.", reply_markup=_admin_detail_keyboard(admin))
        await state.clear()
        return

    current_root = admin.get("root_menu") or "main"
    parent = menu.get("parent")
    keyboard_rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="✅ اختار النود دي", callback_data="adm_scope_pick_current")]
    ]

    nav_targets: list[str] = []
    for row in menu.get("buttons", []):
        keyboard_row = []
        for button_text in row:
            if button_text == "⬅️ Back" or not await db.menu_exists(button_text):
                continue
            nav_targets.append(button_text)
            keyboard_row.append(
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"adm_scope_nav:{len(nav_targets) - 1}",
                )
            )
        if keyboard_row:
            keyboard_rows.append(keyboard_row)

    if parent and await db.menu_exists(parent):
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="adm_scope_up")])
    keyboard_rows.append([InlineKeyboardButton(text="⬅️ رجوع لإعدادات المشرف", callback_data=f"adm:{int(user_id)}")])

    await state.update_data(
        target_admin_id=int(user_id),
        scope_current_menu=menu_name,
        scope_parent_menu=parent,
        scope_nav_targets=nav_targets,
    )
    name = escape(admin.get("name") or str(admin["user_id"]))
    selected_marker = " ✅" if menu_name == current_root else ""

    await message.edit_text(
        "📍 <b>اختيار النود</b>\n\n"
        f"👤 المشرف: {name}\n"
        f"النود الحالية: <code>{escape(current_root)}</code>\n"
        f"أنت الآن داخل: <code>{escape(menu_name)}</code>{selected_marker}\n\n"
        f"{escape(menu.get('text') or menu_name)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
        parse_mode="HTML",
    )


def _format_admin_detail(admin: dict) -> str:
    permissions = admin.get("permissions", [])
    if permissions:
        permission_lines = "\n".join(
            f"• {PERMISSION_BY_CODE[permission].label}"
            for permission in permissions
            if permission in PERMISSION_BY_CODE
        )
    else:
        permission_lines = "لا توجد صلاحيات مفعلة."

    status = "مفعل" if admin["is_active"] else "متوقف"
    name = escape(admin.get("name") or "بدون اسم")
    root_menu = escape(admin.get("root_menu") or "main")
    return (
        "👥 <b>بيانات المشرف</b>\n\n"
        f"🆔 <b>ID:</b> <code>{admin['user_id']}</code>\n"
        f"👤 <b>الاسم:</b> {name}\n"
        f"📍 <b>النود:</b> <code>{root_menu}</code>\n"
        f"⚙️ <b>الحالة:</b> {status}\n\n"
        f"🔐 <b>الصلاحيات:</b>\n{permission_lines}"
    )


async def _show_admin_detail(message: Message, user_id: int) -> None:
    admin = await db.get_admin_user(user_id)
    if not admin:
        await message.edit_text("❌ المشرف غير موجود.", reply_markup=_admins_keyboard(await db.list_admin_users()))
        return
    await message.edit_text(
        _format_admin_detail(admin),
        reply_markup=_admin_detail_keyboard(admin),
        parse_mode="HTML",
    )


async def _ensure_owner(event: CallbackQuery | Message) -> bool:
    user = event.from_user
    if user and is_owner(user.id):
        return True
    if isinstance(event, CallbackQuery):
        await deny_callback(event, "❌ إدارة المشرفين متاحة للمالك فقط.")
    else:
        await deny_message(event, "❌ إدارة المشرفين متاحة للمالك فقط.")
    return False


@router.callback_query(F.data == "admins")
async def cb_admins(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_owner(callback):
        return
    await callback.answer()
    await state.clear()
    admins = await db.list_admin_users()
    await callback.message.edit_text(
        "👥 <b>إدارة المشرفين</b>\n\nاختر مشرفاً لتعديل النود أو الصلاحيات.",
        reply_markup=_admins_keyboard(admins),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "adm_add")
async def cb_add_admin(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_owner(callback):
        return
    await callback.answer()
    await callback.message.answer(
        "أرسل Telegram ID للمشرف الجديد.\n"
        "يمكنك كتابة الاسم بعده اختيارياً، مثال: <code>123456 Ahmed</code>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminManageStates.waiting_admin_id)


@router.message(AdminManageStates.waiting_admin_id)
async def on_admin_id(message: Message, state: FSMContext):
    if not await _ensure_owner(message):
        await state.clear()
        return

    raw = (message.text or "").strip()
    user_id_text, _, name = raw.partition(" ")
    if not user_id_text.isdigit():
        await message.answer("❌ أرسل ID رقمي صحيح.")
        return

    user_id = int(user_id_text)
    if is_owner(user_id):
        await message.answer("هذا المستخدم موجود بالفعل كمالك من ADMIN_IDS.")
        await state.clear()
        await remove_reply_keyboard(message)
        return

    await db.upsert_admin_user(
        user_id=user_id,
        name=name.strip() or None,
        root_menu="main",
        permissions=[VIEW_MENUS],
        is_active=True,
    )
    await state.clear()
    await remove_reply_keyboard(message)
    admin = await db.get_admin_user(user_id)
    await message.answer(
        "✅ تم إضافة المشرف. يمكنك الآن تحديد النود والصلاحيات.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="فتح الإعدادات", callback_data=f"adm:{user_id}")]]
        ),
    )
    if admin:
        await message.answer(
            _format_admin_detail(admin),
            reply_markup=_admin_detail_keyboard(admin),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("adm:"))
async def cb_admin_detail(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_owner(callback):
        return
    await callback.answer()
    await state.clear()
    user_id = int(callback.data.split(":", 1)[1])
    await _show_admin_detail(callback.message, user_id)


@router.callback_query(F.data.startswith("adm_perm:"))
async def cb_toggle_admin_permission(callback: CallbackQuery):
    if not await _ensure_owner(callback):
        return
    _, user_id_text, permission = callback.data.split(":", 2)
    if permission not in PERMISSION_BY_CODE:
        await callback.answer("صلاحية غير معروفة.", show_alert=True)
        return

    user_id = int(user_id_text)
    admin = await db.get_admin_user(user_id)
    if not admin:
        await callback.answer("المشرف غير موجود.", show_alert=True)
        return

    await callback.answer()
    permissions = set(admin.get("permissions", []))
    if permission in permissions:
        permissions.remove(permission)
    else:
        permissions.add(permission)
    ordered = [code for code in ALL_PERMISSION_CODES if code in permissions]
    await db.set_admin_permissions(user_id, ordered)
    await _show_admin_detail(callback.message, user_id)


@router.callback_query(F.data.startswith("adm_all:"))
async def cb_grant_all(callback: CallbackQuery):
    if not await _ensure_owner(callback):
        return
    user_id = int(callback.data.split(":", 1)[1])
    if not await db.get_admin_user(user_id):
        await callback.answer("المشرف غير موجود.", show_alert=True)
        return
    await callback.answer()
    await db.set_admin_permissions(user_id, list(ALL_PERMISSION_CODES))
    await _show_admin_detail(callback.message, user_id)


@router.callback_query(F.data.startswith("adm_none:"))
async def cb_clear_all(callback: CallbackQuery):
    if not await _ensure_owner(callback):
        return
    user_id = int(callback.data.split(":", 1)[1])
    if not await db.get_admin_user(user_id):
        await callback.answer("المشرف غير موجود.", show_alert=True)
        return
    await callback.answer()
    await db.set_admin_permissions(user_id, [])
    await _show_admin_detail(callback.message, user_id)


@router.callback_query(F.data.startswith("adm_scope:"))
async def cb_admin_scope(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_owner(callback):
        return
    user_id = int(callback.data.split(":", 1)[1])
    if not await db.get_admin_user(user_id):
        await callback.answer("المشرف غير موجود.", show_alert=True)
        return
    await callback.answer()
    start_menu = "main" if await db.menu_exists("main") else None
    if start_menu is None:
        menu_names = await db.list_menu_names()
        start_menu = menu_names[0] if menu_names else None
    if not start_menu:
        await callback.answer("لا توجد قوائم متاحة للاختيار.", show_alert=True)
        return
    await state.update_data(target_admin_id=user_id)
    await state.set_state(AdminManageStates.waiting_admin_scope)
    await _show_scope_picker(callback.message, state, start_menu)


@router.callback_query(F.data.startswith("adm_scope_nav:"), AdminManageStates.waiting_admin_scope)
async def cb_admin_scope_nav(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_owner(callback):
        return
    data = await state.get_data()
    nav_targets = data.get("scope_nav_targets") or []
    index = int(callback.data.split(":", 1)[1])
    if index < 0 or index >= len(nav_targets):
        await callback.answer("اختيار غير صالح. افتح اختيار النود مرة أخرى.", show_alert=True)
        return
    target_menu = nav_targets[index]
    if not await db.menu_exists(target_menu):
        await callback.answer("القائمة دي اتحذفت أو مش موجودة.", show_alert=True)
        return
    await callback.answer()
    await _show_scope_picker(callback.message, state, target_menu)


@router.callback_query(F.data == "adm_scope_up", AdminManageStates.waiting_admin_scope)
async def cb_admin_scope_up(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_owner(callback):
        return
    data = await state.get_data()
    parent = data.get("scope_parent_menu")
    if not parent or not await db.menu_exists(parent):
        await callback.answer("لا يوجد رجوع من هنا.", show_alert=True)
        return
    await callback.answer()
    await _show_scope_picker(callback.message, state, parent)


@router.callback_query(F.data == "adm_scope_pick_current", AdminManageStates.waiting_admin_scope)
async def cb_admin_scope_pick_current(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_owner(callback):
        return
    data = await state.get_data()
    user_id = data.get("target_admin_id")
    root_menu = data.get("scope_current_menu")
    if not user_id:
        await state.clear()
        await callback.answer("انتهت الجلسة. افتح إدارة المشرفين مرة أخرى.", show_alert=True)
        return
    if not root_menu or not await db.menu_exists(root_menu):
        await callback.answer("هذه القائمة غير موجودة أو تم حذفها.", show_alert=True)
        return

    await db.set_admin_root_menu(int(user_id), root_menu)
    await state.clear()
    admin = await db.get_admin_user(int(user_id))
    await callback.answer("✅ تم تحديث النود")
    if admin:
        await callback.message.edit_text(
            _format_admin_detail(admin),
            reply_markup=_admin_detail_keyboard(admin),
            parse_mode="HTML",
        )


@router.message(AdminManageStates.waiting_admin_scope)
async def on_admin_scope_text(message: Message):
    if not await _ensure_owner(message):
        return
    await message.answer("اختار النود من الأزرار الموجودة في الرسالة فوق.")


@router.callback_query(F.data.startswith("adm_active:"))
async def cb_toggle_admin_active(callback: CallbackQuery):
    if not await _ensure_owner(callback):
        return
    user_id = int(callback.data.split(":", 1)[1])
    admin = await db.get_admin_user(user_id)
    if not admin:
        await callback.answer("المشرف غير موجود.", show_alert=True)
        return
    await callback.answer()
    await db.set_admin_active(user_id, not admin["is_active"])
    await _show_admin_detail(callback.message, user_id)


@router.callback_query(F.data.startswith("adm_del:"))
async def cb_delete_admin(callback: CallbackQuery):
    if not await _ensure_owner(callback):
        return
    user_id = int(callback.data.split(":", 1)[1])
    if not await db.get_admin_user(user_id):
        await callback.answer("المشرف غير موجود.", show_alert=True)
        return
    await callback.answer()
    await db.delete_admin_user(user_id)
    admins = await db.list_admin_users()
    await callback.message.edit_text(
        "✅ تم حذف المشرف.\n\n👥 <b>إدارة المشرفين</b>",
        reply_markup=_admins_keyboard(admins),
        parse_mode="HTML",
    )
