from typing import Optional, List, Dict, Any
from collections import defaultdict

from core.database import db
from menu_manager.constants import BACK_BUTTON, MAX_NAME_BYTES
from menu_manager.exceptions import (
    MenuNotFoundError,
    MenuAlreadyExistsError,
    NameTooLongError,
    CircularReferenceError,
)

# ──────────────────────────────────────────────
#  Helper Functions (internal)
# ──────────────────────────────────────────────

def _validate_name_length(name: str) -> None:
    """Ensure a name fits within Telegram's callback_data byte limit."""
    byte_len = len(name.encode('utf-8'))
    if byte_len > MAX_NAME_BYTES:
        raise NameTooLongError(
            f"الاسم '{name}' طويل جداً ({byte_len} بايت). "
            f"الحد الأقصى المسموح هو {MAX_NAME_BYTES} بايت."
        )


async def _ensure_menu_exists(name: str) -> None:
    if not await db.menu_exists(name):
        raise MenuNotFoundError(f"Menu '{name}' not found")


async def _ensure_menu_does_not_exist(name: str) -> None:
    if await db.menu_exists(name):
        raise MenuAlreadyExistsError(f"Menu '{name}' already exists")


async def _fetch_menu(name: str) -> dict:
    """Fetch menu from DB and ensure it strictly matches MenuData TypedDict."""
    data = await db.get_menu(name)
    if data and "name" not in data:
        data["name"] = name
    return data


async def _remove_button_from_parent(name: str) -> None:
    """Remove a menu's button from its parent."""
    menu = await db.get_menu(name)
    if menu is None:
        return

    parent = menu.get("parent")
    if parent and await db.menu_exists(parent):
        buttons = await db.get_menu_buttons(parent)
        for row in buttons:
            if name in row:
                row.remove(name)
                break

        # Remove empty rows
        buttons = [row for row in buttons if row]
        await db.update_menu_field(parent, "buttons", buttons)


async def _add_button_to_menu(menu_name: str, button_text: str, row: Optional[int] = None) -> None:
    """Add a button to a menu, before the Back button if it exists, or in a specific row."""
    buttons = await db.get_menu_buttons(menu_name)

    # Prevent silent duplicates
    if any(button_text in r for r in buttons):
        return

    has_back = False
    for r in buttons:
        if BACK_BUTTON in r:
            has_back = True
            r.remove(BACK_BUTTON)
            break

    buttons = [r for r in buttons if r]

    if row is not None:
        while len(buttons) <= row:
            buttons.append([])
        buttons[row].append(button_text)
    else:
        buttons.append([button_text])

    if has_back:
        buttons.append([BACK_BUTTON])

    await db.update_menu_field(menu_name, "buttons", buttons)


def _check_circular_reference_from_cache(menu_name: str, new_parent: str,
                                          cache: Dict[str, Any]) -> None:
    """
    Walk the parent chain in O(D) dict lookups instead of O(D) DB queries.

    Uses the in-memory cache that is guaranteed to be up-to-date after any
    reload_menu / reload_menus call.  Falls back gracefully if a key is
    missing from the cache (stale or cold cache) — in that case we simply
    stop the walk early rather than raising a false positive.

    Args:
        menu_name:  The menu being re-parented.
        new_parent: The proposed new parent to check.
        cache:      The _MENUS_CACHE dict from core.loader.
    """
    current = new_parent
    # Guard against infinite loops in a corrupt DB (depth cap = len(cache) + 1)
    max_steps = len(cache) + 1
    steps = 0

    while current and steps < max_steps:
        if current == menu_name:
            raise CircularReferenceError(
                f"Cannot set '{new_parent}' as parent of '{menu_name}' "
                f"because it creates a circular reference."
            )
        entry = cache.get(current)
        if entry is None:
            # Key not in cache — stop walking rather than hitting DB.
            # The DB-level FK constraints and rename atomicity protect us.
            break
        current = entry.get("parent")
        steps += 1


async def _check_circular_reference(menu_name: str, new_parent: str) -> None:
    """
    Ensure the new_parent is not a descendant of menu_name.

    Phase 3 optimisation: read from the in-memory cache first.
    If the cache is warm (post-startup or post-reload), this is O(D) dict
    lookups with zero DB round-trips.  If the cache is cold (e.g. the very
    first call before any reload), we fall back to the original DB walk.
    """
    # Import here to avoid a circular import at module load time.
    from core.loader import get_menus
    cache = get_menus()

    if cache:
        # Fast path: all menus in RAM — no DB round-trip needed.
        _check_circular_reference_from_cache(menu_name, new_parent, cache)
    else:
        # Cold-cache fallback: walk via DB (original behaviour).
        current_parent = new_parent
        while current_parent:
            if current_parent == menu_name:
                raise CircularReferenceError(
                    f"Cannot set '{new_parent}' as parent of '{menu_name}' "
                    f"because it creates a circular reference."
                )
            parent_menu = await db.get_menu(current_parent)
            current_parent = parent_menu.get("parent") if parent_menu else None


def _collect_subtree(root: str, cache: Dict[str, Any]) -> List[str]:
    """
    Return all node names in the subtree rooted at *root* (root included),
    gathered from the in-memory cache with a single BFS pass — O(K) where K
    is the subtree size, with zero DB round-trips.

    Falls back to an empty list only if *root* itself is absent from the
    cache, which should never happen in normal operation.
    """
    if root not in cache:
        return []

    # Build a children_map once — same technique used by get_tree().
    children_map: Dict[str, List[str]] = defaultdict(list)
    for name, data in cache.items():
        p = data.get("parent")
        if p is not None:
            children_map[p].append(name)

    # BFS collect
    result: List[str] = []
    queue = [root]
    while queue:
        node = queue.pop()
        result.append(node)
        queue.extend(children_map.get(node, []))

    return result


def _invalidate_subtree_cache(names: List[str]) -> None:
    """
    Remove all *names* from the in-memory menus cache in O(K).

    Called after a successful batch-delete so the cache instantly reflects
    the DB state without waiting for a full reload_menus() call.
    """
    from core.loader import _MENUS_CACHE  # module-level dict — mutate in-place
    for n in names:
        _MENUS_CACHE.pop(n, None)
