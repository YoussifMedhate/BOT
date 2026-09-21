"""Small runtime adaptations for the operating system running the bot."""

from __future__ import annotations

import asyncio
import sys


def configure_event_loop_policy() -> bool:
    """Enable uvloop where it is supported and available.

    uvloop is intentionally not installed on Windows.  Returning ``False`` in
    that case leaves Python's default Proactor event loop in place, which is
    the supported Windows implementation.
    """
    if sys.platform == "win32":
        return False

    try:
        import uvloop
    except ImportError:
        return False

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    return True
