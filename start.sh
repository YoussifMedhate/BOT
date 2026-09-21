#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python="$project_root/.venv/bin/python"

if [ ! -x "$python" ]; then
    printf '%s\n' "Virtual environment not found. Create it first with: python3.11 -m venv .venv" >&2
    exit 1
fi

exec "$python" "$project_root/run.py" "$@"
