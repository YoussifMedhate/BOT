# ──────────────────────────────────────────────
#  Custom Exceptions
# ──────────────────────────────────────────────

class MenuError(Exception):
    """Base exception class for menu operations."""
    pass

class MenuNotFoundError(MenuError):
    """Raised when a menu does not exist."""
    pass

class MenuAlreadyExistsError(MenuError):
    """Raised when attempting to create a menu that already exists."""
    pass

class CircularReferenceError(MenuError):
    """Raised when setting a parent would create a circular dependency."""
    pass

class ButtonDuplicateError(MenuError):
    """Raised when adding a button that already exists in the menu."""
    pass

class ProtectedMenuError(MenuError):
    """Raised when attempting to modify or delete a protected menu like 'main'."""
    pass

class NameTooLongError(MenuError):
    """Raised when a menu or button name exceeds Telegram's callback_data byte limit."""
    pass
