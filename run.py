"""Cross-platform command-line launcher for the Telegram bots.

Run ``python run.py --help`` for the available targets.  Imports that require
the bot configuration are deliberately deferred so ``--check`` and ``--help``
work on a freshly cloned project before ``.env`` has been configured.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import sys


MINIMUM_PYTHON = (3, 11)
TARGETS = ("all", "admin", "main", "dev")
REQUIRED_MODULES = ("aiogram", "dotenv", "psutil")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one or more Telegram bot processes.")
    parser.add_argument(
        "target",
        choices=TARGETS,
        default="all",
        nargs="?",
        help="bot process to run (default: all)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the Python runtime and installed dependencies without starting a bot",
    )
    return parser.parse_args()


def check_runtime() -> int:
    """Perform a configuration-independent dependency check."""
    errors: list[str] = []

    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        current = ".".join(map(str, sys.version_info[:3]))
        errors.append(f"Python {required}+ is required; found Python {current}.")

    for module_name in REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"Cannot import {module_name}: {exc}")

    if errors:
        print("Runtime check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        "Runtime check passed "
        f"(Python {'.'.join(map(str, sys.version_info[:3]))} on {sys.platform})."
    )
    return 0


async def run_target(target: str) -> None:
    """Load and run only the selected target after argument validation."""
    if target == "all":
        from run_admin_and_main import start_all

        await start_all()
        return

    if target == "admin":
        from run_admin import main
    elif target == "main":
        from run_main import main
    else:
        from run_dev import main

    await main()


def main() -> int:
    args = parse_args()
    if args.check:
        return check_runtime()

    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        print(f"Python {required}+ is required.", file=sys.stderr)
        return 1

    try:
        asyncio.run(run_target(args.target))
    except KeyboardInterrupt:
        print("Stopped.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
