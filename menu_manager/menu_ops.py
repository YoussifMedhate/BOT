import copy
from typing import Optional, List, Dict
from collections import defaultdict

from core.database import db
from menu_manager.constants import BACK_BUTTON, MAIN_MENU_NAME
from menu_manager.exceptions import ProtectedMenuError
from menu_manager.helpers import (
    _validate_name_length,
    _ensure_menu_exists,
    _ensure_menu_does_not_exist,
    _fetch_menu,
    _remove_button_from_parent,
    _add_button_to_menu,
    _check_circular_reference,
    _collect_subtree,
    _invalidate_subtree_cache,
)

# ──────────────────────────────────────────────
#  Menu Operations
# ──────────────────────────────────────────────

async def add_menu(
    name: str,
    parent: Optional[str] = None,
    text: Optional[str] = None,
    buttons: Optional[List[List[str]]] = None,
    add_back_button: bool = True,
    row: Optional[int] = None
) -> dict:
    """Add a new menu."""
    _validate_name_length(name)
    await _ensure_menu_does_not_exist(name)

    if parent:
        await _ensure_menu_exists(parent)

    if buttons is None:
        buttons = []

    if add_back_button and parent:
        has_back = any(BACK_BUTTON in r for r in buttons)
        if not has_back:
            buttons.append([BACK_BUTTON])

    await db.upsert_menu(name, parent, text or name, buttons)
    if parent:
        await _add_button_to_menu(parent, name, row=row)

    return await _fetch_menu(name)


async def delete_menu(name: str, delete_children: bool = False) -> bool:
    """
    Delete a menu. Returns True on success.

    Phase 3 optimisation (delete_children=True path):
    ──────────────────────────────────────────────────
    Before: recursive DFS that issued one DELETE + COMMIT per node  → O(K) commits.
    After:  BFS subtree collection from the in-memory cache (0 DB reads), then a
            single _execute_transaction() that deletes all K rows in 1 commit,
            followed by a precise cache eviction for all removed keys.

    The flat (delete_children=False) path is unchanged.
    """
    await _ensure_menu_exists(name)

    if name == MAIN_MENU_NAME:
        raise ProtectedMenuError("Cannot delete the main menu")

    menu = await db.get_menu(name)
    parent = menu.get("parent")
    children = await db.get_children(name)

    if delete_children:
        from core.loader import get_menus
        cache = get_menus()

        if cache:
            # ── Fast path: collect subtree from RAM, delete in 1 transaction ──
            subtree = _collect_subtree(name, cache)

            # Remove the root's button from its parent first (still needs DB).
            if parent:
                await _remove_button_from_parent(name)

            # Batch-delete every node in a single atomic transaction.
            statements = [
                ("DELETE FROM menus WHERE name = ?", (node,))
                for node in subtree
            ]
            await db._execute_transaction(statements)

            # Precise cache eviction — no full reload needed.
            _invalidate_subtree_cache(subtree)

        else:
            # ── Cold-cache fallback: original recursive approach ──
            async def _delete_recursive(menu_name: str) -> None:
                for child in await db.get_children(menu_name):
                    await _delete_recursive(child)
                await _remove_button_from_parent(menu_name)
                await db.delete_menu_from_db(menu_name)

            await _delete_recursive(name)

    else:
        # Flat delete: re-parent direct children to grandparent.
        for child in children:
            await db.update_menu_field(child, "parent", parent)
            if parent:
                await _add_button_to_menu(parent, child)

        await _remove_button_from_parent(name)
        await db.delete_menu_from_db(name)

    return True


async def rename_menu(old_name: str, new_name: str) -> dict:
    """Rename a menu. Updates all references."""
    _validate_name_length(new_name)
    await _ensure_menu_exists(old_name)
    await _ensure_menu_does_not_exist(new_name)

    await db.rename_menu_in_db(old_name, new_name)

    return await _fetch_menu(new_name)


async def update_text(name: str, text: str) -> dict:
    """Update the display text of a menu."""
    await _ensure_menu_exists(name)
    await db.update_menu_field(name, "text", text)
    return await _fetch_menu(name)


async def set_parent(name: str, new_parent: Optional[str]) -> dict:
    """Move a menu under a different parent."""
    await _ensure_menu_exists(name)

    if new_parent:
        await _ensure_menu_exists(new_parent)
        await _check_circular_reference(name, new_parent)

    menu = await db.get_menu(name)
    old_parent = menu.get("parent")

    # Early return if no change is needed
    if old_parent == new_parent:
        return await _fetch_menu(name)

    if old_parent:
        await _remove_button_from_parent(name)

    if new_parent:
        await _add_button_to_menu(new_parent, name)

    await db.update_menu_field(name, "parent", new_parent)

    buttons = await db.get_menu_buttons(name)
    has_back = any(BACK_BUTTON in row for row in buttons)

    if new_parent and not has_back:
        buttons.append([BACK_BUTTON])
        await db.update_menu_field(name, "buttons", buttons)
    elif not new_parent and has_back:
        buttons = [row for row in buttons if BACK_BUTTON not in row]
        await db.update_menu_field(name, "buttons", buttons)

    return await _fetch_menu(name)


async def get_menu(name: str) -> dict:
    """Get a menu's details."""
    await _ensure_menu_exists(name)
    return await _fetch_menu(name)


async def list_menus() -> List[str]:
    """List all menu names."""
    return await db.list_menu_names()


async def get_children(name: str, menus: Optional[Dict] = None) -> List[str]:
    """Get direct children of a menu."""
    if menus is not None:
        return [
            key for key, menu in menus.items()
            if menu.get("parent") == name
        ]
    return await db.get_children(name)


async def get_tree(name: str = MAIN_MENU_NAME, menus: Optional[Dict] = None) -> str:
    """
    Get a visual tree of menu hierarchy.
    Optimized to O(N) by building a children map once.
    Includes safeguard against DB corruption (Infinite Recursion).
    """
    if menus is None:
        menus = await db.get_all_menus()

    # Build adjacency list once (O(N))
    children_map = defaultdict(list)
    for m_name, m_data in menus.items():
        p = m_data.get("parent")
        if p is not None:
            children_map[p].append(m_name)

    lines = []

    def _build_tree(current_name: str, indent: int, visited: set) -> None:
        if current_name in visited:
            lines.append(f"{'  ' * indent}⚠️ [Circular Reference Detected: {current_name}]")
            return

        visited.add(current_name)
        prefix = "  " * indent
        children = children_map.get(current_name, [])
        icon = "📁" if children else "📄"

        lines.append(f"{prefix}{icon} {current_name}")
        for child in children:
            _build_tree(child, indent + 1, visited)
        visited.remove(current_name)

    _build_tree(name, 0, set())
    return "\n".join(lines) + "\n"


async def duplicate_menu(name: str, new_name: str, new_parent: Optional[str] = None) -> dict:
    """Duplicate a menu (without its children)."""
    await _ensure_menu_exists(name)
    await _ensure_menu_does_not_exist(new_name)

    if new_parent:
        await _ensure_menu_exists(new_parent)

    menu = await db.get_menu(name)
    parent = new_parent or menu.get("parent")
    new_buttons = copy.deepcopy(menu.get("buttons", []))

    await db.upsert_menu(new_name, parent, new_name, new_buttons)
    if parent and await db.menu_exists(parent):
        await _add_button_to_menu(parent, new_name)

    return await _fetch_menu(new_name)
