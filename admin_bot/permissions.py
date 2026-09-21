from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from aiogram.types import CallbackQuery, Message

from config.settings import ADMIN_IDS
from core.database import db


MAIN_MENU = "main"


@dataclass(frozen=True)
class PermissionDef:
    code: str
    label: str


VIEW_MENUS = "view_menus"
EDIT_MENU_TEXT = "edit_menu_text"
MOVE_MENU = "move_menu"
DUPLICATE_MENU = "duplicate_menu"
ADD_BUTTONS = "add_buttons"
DELETE_BUTTONS = "delete_buttons"
REORDER_BUTTONS = "reorder_buttons"
DELETE_MENUS = "delete_menus"
ADD_MATERIALS = "add_materials"
DELETE_MATERIALS = "delete_materials"
REORDER_MATERIALS = "reorder_materials"
BROADCAST = "broadcast"
BACKUP = "backup"
ANALYTICS = "analytics"


PERMISSIONS: tuple[PermissionDef, ...] = (
    PermissionDef(VIEW_MENUS, "عرض القوائم"),
    PermissionDef(EDIT_MENU_TEXT, "تغيير نص القائمة"),
    PermissionDef(MOVE_MENU, "تغيير الأب"),
    PermissionDef(DUPLICATE_MENU, "نسخ القوائم"),
    PermissionDef(ADD_BUTTONS, "إضافة أزرار وقوائم"),
    PermissionDef(DELETE_BUTTONS, "حذف الأزرار"),
    PermissionDef(REORDER_BUTTONS, "ترتيب الأزرار"),
    PermissionDef(DELETE_MENUS, "حذف القوائم"),
    PermissionDef(ADD_MATERIALS, "إضافة ملفات ونصوص"),
    PermissionDef(DELETE_MATERIALS, "حذف الملفات والنصوص"),
    PermissionDef(REORDER_MATERIALS, "ترتيب الملفات"),
    PermissionDef(BROADCAST, "إذاعة للجميع"),
    PermissionDef(BACKUP, "الباك أب والاستعادة"),
    PermissionDef(ANALYTICS, "الإحصائيات"),
)

PERMISSION_BY_CODE = {permission.code: permission for permission in PERMISSIONS}
ALL_PERMISSION_CODES = tuple(PERMISSION_BY_CODE)
MENU_AREA_PERMISSIONS = frozenset(
    {
        VIEW_MENUS,
        EDIT_MENU_TEXT,
        MOVE_MENU,
        DUPLICATE_MENU,
        ADD_BUTTONS,
        DELETE_BUTTONS,
        REORDER_BUTTONS,
        DELETE_MENUS,
        ADD_MATERIALS,
        DELETE_MATERIALS,
        REORDER_MATERIALS,
    }
)
MATERIAL_PERMISSIONS = frozenset({ADD_MATERIALS, DELETE_MATERIALS, REORDER_MATERIALS})


def is_owner(user_id: int | None) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


async def get_admin_permissions(user_id: int | None) -> set[str]:
    if user_id is None:
        return set()
    if is_owner(user_id):
        return set(ALL_PERMISSION_CODES)

    admin = await db.get_admin_user(user_id)
    if not admin or not admin.get("is_active"):
        return set()
    return set(admin.get("permissions", []))


async def get_admin_scope(user_id: int | None) -> str:
    if user_id is None or is_owner(user_id):
        return MAIN_MENU

    admin = await db.get_admin_user(user_id)
    if not admin:
        return MAIN_MENU
    return admin.get("root_menu") or MAIN_MENU


async def has_permission(user_id: int | None, permission: str) -> bool:
    return permission in await get_admin_permissions(user_id)


async def has_any_permission(user_id: int | None, permissions: Iterable[str]) -> bool:
    user_permissions = await get_admin_permissions(user_id)
    return any(permission in user_permissions for permission in permissions)


async def is_allowed_admin(user_id: int | None) -> bool:
    if is_owner(user_id):
        return True
    if user_id is None:
        return False
    admin = await db.get_admin_user(user_id)
    return bool(admin and admin.get("is_active"))


async def is_menu_in_scope(user_id: int | None, menu_name: str | None) -> bool:
    if not menu_name:
        return False
    if is_owner(user_id):
        return True

    root_menu = await get_admin_scope(user_id)
    if root_menu == MAIN_MENU or menu_name == root_menu:
        return True

    current = menu_name
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        menu = await db.get_menu(current)
        if not menu:
            return False
        parent = menu.get("parent")
        if parent == root_menu:
            return True
        current = parent
    return False


async def deny_callback(callback: CallbackQuery, text: str = "❌ لا تملك صلاحية هذه العملية.") -> None:
    await callback.answer(text, show_alert=True)


async def deny_message(message: Message, text: str = "❌ لا تملك صلاحية هذه العملية.") -> None:
    await message.answer(text)


async def require_callback_permission(callback: CallbackQuery, permission: str) -> bool:
    if await has_permission(callback.from_user.id if callback.from_user else None, permission):
        return True
    await deny_callback(callback)
    return False


async def require_message_permission(message: Message, permission: str) -> bool:
    if await has_permission(message.from_user.id if message.from_user else None, permission):
        return True
    await deny_message(message)
    return False


async def require_callback_menu_scope(callback: CallbackQuery, menu_name: str) -> bool:
    if await is_menu_in_scope(callback.from_user.id if callback.from_user else None, menu_name):
        return True
    await deny_callback(callback, "❌ هذه القائمة خارج النطاق المسموح لك.")
    return False


async def require_message_menu_scope(message: Message, menu_name: str) -> bool:
    if await is_menu_in_scope(message.from_user.id if message.from_user else None, menu_name):
        return True
    await deny_message(message, "❌ هذه القائمة خارج النطاق المسموح لك.")
    return False
