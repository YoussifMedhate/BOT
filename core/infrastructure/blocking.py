from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

_blocking_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="blocking")


async def run_blocking(fn: Callable, *args, **kwargs) -> Any:
    """Run a blocking callable in the thread pool without blocking the event loop.

    Uses asyncio.wrap_future() so the event loop is properly suspended (not
    busy-polled) until the thread completes its work.
    """
    loop = asyncio.get_running_loop()
    future = _blocking_executor.submit(partial(fn, *args, **kwargs))
    return await asyncio.wrap_future(future, loop=loop)

