from typing import Optional, List, TypedDict

# ──────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────

BACK_BUTTON = "⬅️ Back"
MAIN_MENU_NAME = "main"

# Telegram limits callback_data to 64 bytes.
# The admin bot uses prefixes like "nav:" (4 bytes), so names must fit in 60 bytes.
MAX_CALLBACK_PREFIX_BYTES = 4  # len("nav:".encode('utf-8'))
MAX_CALLBACK_DATA_BYTES = 64
MAX_NAME_BYTES = MAX_CALLBACK_DATA_BYTES - MAX_CALLBACK_PREFIX_BYTES  # 60


# ──────────────────────────────────────────────
#  Types
# ──────────────────────────────────────────────

class MenuData(TypedDict):
    """Type definition for a Menu object returned by the database."""
    name: str
    parent: Optional[str]
    text: str
    buttons: List[List[str]]
