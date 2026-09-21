from typing import Optional, List

from core.database import db
from menu_manager.constants import BACK_BUTTON
from menu_manager.exceptions import ButtonDuplicateError
from menu_manager.helpers import (
    _validate_name_length,
    _ensure_menu_exists,
    _fetch_menu,
)

# ──────────────────────────────────────────────
#  Button Operations
# ──────────────────────────────────────────────

async def add_button(
    menu_name: str,
    button_text: str,
    row: Optional[int] = None,
    position: Optional[int] = None
) -> dict:
    """Add a button to a menu."""
    _validate_name_length(button_text)
    await _ensure_menu_exists(menu_name)

    buttons = await db.get_menu_buttons(menu_name)

    if any(button_text in r for r in buttons):
        raise ButtonDuplicateError(f"Button '{button_text}' already exists in '{menu_name}'")

    has_back = False
    for r in buttons:
        if BACK_BUTTON in r:
            has_back = True
            r.remove(BACK_BUTTON)
            break

    buttons = [r for r in buttons if r]

    if row is not None:
        if row < 0:
            raise ValueError(f"Row {row} cannot be negative")

        while len(buttons) <= row:
            buttons.append([])

        if position is not None:
            if position < 0:
                raise ValueError("Position cannot be negative")
            buttons[row].insert(position, button_text)
        else:
            buttons[row].append(button_text)
    else:
        buttons.append([button_text])

    if has_back:
        buttons.append([BACK_BUTTON])

    await db.update_menu_field(menu_name, "buttons", buttons)
    await db.sync_custom_button_locations_for_menu(menu_name)
    return await _fetch_menu(menu_name)


async def remove_button(menu_name: str, button_text: str) -> dict:
    """Remove a button from a menu."""
    await _ensure_menu_exists(menu_name)

    buttons = await db.get_menu_buttons(menu_name)
    found = False

    for row in buttons:
        if button_text in row:
            row.remove(button_text)
            found = True
            break

    buttons = [row for row in buttons if row]

    if not found:
        raise ValueError(f"Button '{button_text}' not found in '{menu_name}'")

    await db.update_menu_field(menu_name, "buttons", buttons)
    await db.sync_custom_button_locations_for_menu(menu_name)
    return await _fetch_menu(menu_name)


async def move_button(
    menu_name: str,
    button_text: str,
    to_row: int,
    to_position: Optional[int] = None
) -> dict:
    """Move a button to a different row/position."""
    await _ensure_menu_exists(menu_name)

    if to_row < 0:
        raise ValueError("to_row cannot be negative")
    if to_position is not None and to_position < 0:
        raise ValueError("to_position cannot be negative")

    buttons = await db.get_menu_buttons(menu_name)

    found = False
    for row in buttons:
        if button_text in row:
            row.remove(button_text)
            found = True
            break

    if not found:
        raise ValueError(f"Button '{button_text}' not found in '{menu_name}'")

    buttons = [row for row in buttons if row]

    while len(buttons) <= to_row:
        buttons.append([])

    if to_position is not None:
        buttons[to_row].insert(to_position, button_text)
    else:
        buttons[to_row].append(button_text)

    await db.update_menu_field(menu_name, "buttons", buttons)
    await db.sync_custom_button_locations_for_menu(menu_name)
    return await _fetch_menu(menu_name)


async def swap_buttons(
    menu_name: str,
    button1: str,
    button2: str
) -> dict:
    """Swap two buttons' positions."""
    await _ensure_menu_exists(menu_name)

    buttons = await db.get_menu_buttons(menu_name)

    pos1 = pos2 = None
    for i, row in enumerate(buttons):
        for j, btn in enumerate(row):
            if btn == button1:
                pos1 = (i, j)
            elif btn == button2:
                pos2 = (i, j)

    if pos1 is None:
        raise ValueError(f"Button '{button1}' not found")
    if pos2 is None:
        raise ValueError(f"Button '{button2}' not found")

    buttons[pos1[0]][pos1[1]] = button2
    buttons[pos2[0]][pos2[1]] = button1

    await db.update_menu_field(menu_name, "buttons", buttons)
    await db.sync_custom_button_locations_for_menu(menu_name)
    return await _fetch_menu(menu_name)


async def set_buttons(menu_name: str, buttons: List[List[str]]) -> dict:
    """Replace all buttons in a menu."""
    await _ensure_menu_exists(menu_name)

    await db.update_menu_field(menu_name, "buttons", buttons)
    await db.sync_custom_button_locations_for_menu(menu_name)
    return await _fetch_menu(menu_name)


async def reorder_rows(menu_name: str, new_order: List[int]) -> dict:
    """Reorder button rows."""
    await _ensure_menu_exists(menu_name)

    buttons = await db.get_menu_buttons(menu_name)

    if sorted(new_order) != list(range(len(buttons))):
        raise ValueError(
            f"new_order must contain all indices 0-{len(buttons)-1}"
        )

    reordered = [buttons[i] for i in new_order]
    await db.update_menu_field(menu_name, "buttons", reordered)
    await db.sync_custom_button_locations_for_menu(menu_name)
    return await _fetch_menu(menu_name)
