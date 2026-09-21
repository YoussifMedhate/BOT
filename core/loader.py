from core.database import db

_MENUS_CACHE: dict = {}
_MATERIALS_CACHE: dict = {}
_CUSTOM_BUTTONS_CACHE: set[str] = set()

async def load_menus():
    """Load all menus from SQLite database into the RAM cache."""
    global _MENUS_CACHE
    _MENUS_CACHE = await db.get_all_menus()

async def load_materials():
    """Load all materials from SQLite database into the RAM cache."""
    global _MATERIALS_CACHE
    _MATERIALS_CACHE = await db.get_all_materials()

async def load_custom_buttons():
    """Load all pending custom button names into the RAM cache."""
    global _CUSTOM_BUTTONS_CACHE
    rows = await db.get_pending_buttons()
    _CUSTOM_BUTTONS_CACHE = {
        row['button_name']
        for row in rows
        if row.get('menu_name') is not None
    }

async def reload_menu(name: str):
    """Refresh one menu entry in the RAM cache."""
    menu = await db.get_menu(name)
    if menu is None:
        _MENUS_CACHE.pop(name, None)
    else:
        _MENUS_CACHE[name] = menu

async def reload_materials_for(menu_name: str):
    """Refresh cached materials for one menu."""
    materials = await db.get_materials(menu_name)
    if materials:
        _MATERIALS_CACHE[menu_name] = materials
    else:
        _MATERIALS_CACHE.pop(menu_name, None)

async def reload_custom_buttons():
    """Refresh cached pending custom button names."""
    await load_custom_buttons()

def get_menus() -> dict:
    """Return the cached menus."""
    return _MENUS_CACHE

def get_menu(name: str) -> dict | None:
    """Return a specific menu from the cache."""
    return _MENUS_CACHE.get(name)

def get_cached_materials(menu_name: str) -> list:
    """Return materials for a specific menu from the cache."""
    return _MATERIALS_CACHE.get(menu_name, [])

def is_cached_custom_button(name: str) -> bool:
    """Check if a button name is a pending custom button (from cache)."""
    return name in _CUSTOM_BUTTONS_CACHE

async def reload_menus():
    """Reload menus, materials, and custom buttons caches."""
    await load_menus()
    await load_materials()
    await load_custom_buttons()
