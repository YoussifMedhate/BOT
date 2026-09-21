import os
from pathlib import Path

from dotenv import load_dotenv

from config import defaults

BASE_DIR = Path(defaults.BASE_DIR)
BOT_ENV = os.getenv("BOT_ENV") or os.getenv("ENV") or defaults.BOT_ENV

# Priority: process environment -> .env.{ENV} -> .env -> defaults.py.
# python-dotenv keeps already-set process variables when override=False.
load_dotenv(BASE_DIR / f".env.{BOT_ENV}", override=False)
load_dotenv(BASE_DIR / ".env", override=False)


def _get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_project_path(name: str, default: str) -> str:
    """Resolve a configured file path relative to the project root.

    A relative value such as ``config/bot.db`` now means the same thing when
    the app is started from PowerShell, Bash, a service manager, or a Procfile.
    Forward slashes are accepted by pathlib on both Windows and Linux.
    """
    raw_path = _get_env(name, default)
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path.resolve())


DB_PATH = _get_project_path("DB_PATH", defaults.DB_PATH)


def _get_int_list(name: str) -> list[int]:
    raw = _get_env(name)
    if not raw:
        return []
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _get_int(name: str, default: int) -> int:
    raw = _get_env(name)
    return int(raw) if raw else default


def _get_float(name: str, default: float) -> float:
    raw = _get_env(name)
    return float(raw) if raw else default


MAIN_BOT_TOKEN = _get_env("MAIN_BOT_TOKEN", "MISSING_TOKEN")
ADMIN_BOT_TOKEN = _get_env("ADMIN_BOT_TOKEN", "MISSING_TOKEN")
DEV_BOT_TOKEN = _get_env("DEV_BOT_TOKEN", "MISSING_TOKEN")

ADMIN_IDS = _get_int_list("ADMIN_IDS")
DEV_IDS = _get_int_list("DEV_IDS")

DEV_CHANNEL_ID = _get_env("DEV_CHANNEL_ID")
BACKUP_CHANNEL_ID = _get_env("BACKUP_CHANNEL_ID")
BACKUP_INTERVAL_HOURS = _get_int("BACKUP_INTERVAL_HOURS", defaults.BACKUP_INTERVAL_HOURS)
BACKUP_RETENTION_DAILY = _get_int("BACKUP_RETENTION_DAILY", defaults.BACKUP_RETENTION_DAILY)
BACKUP_RETENTION_WEEKLY = _get_int("BACKUP_RETENTION_WEEKLY", defaults.BACKUP_RETENTION_WEEKLY)
BACKUP_RETENTION_MONTHLY = _get_int("BACKUP_RETENTION_MONTHLY", defaults.BACKUP_RETENTION_MONTHLY)

ANALYTICS_QUEUE_MAX_SIZE = _get_int(
    "ANALYTICS_QUEUE_MAX_SIZE",
    defaults.ANALYTICS_QUEUE_MAX_SIZE,
)
ANALYTICS_FLUSH_INTERVAL_SECONDS = _get_float(
    "ANALYTICS_FLUSH_INTERVAL_SECONDS",
    defaults.ANALYTICS_FLUSH_INTERVAL_SECONDS,
)
ANALYTICS_BATCH_SIZE = _get_int("ANALYTICS_BATCH_SIZE", defaults.ANALYTICS_BATCH_SIZE)
ANALYTICS_DEAD_LETTER_PATH = _get_project_path(
    "ANALYTICS_DEAD_LETTER_PATH",
    defaults.ANALYTICS_DEAD_LETTER_PATH,
)

RATE_LIMIT_WINDOW_SECONDS = _get_float(
    "RATE_LIMIT_WINDOW_SECONDS",
    defaults.RATE_LIMIT_WINDOW_SECONDS,
)
RATE_LIMIT_MAX_EVENTS = _get_int("RATE_LIMIT_MAX_EVENTS", defaults.RATE_LIMIT_MAX_EVENTS)

ALERT_QUEUE_THRESHOLD_RATIO = _get_float(
    "ALERT_QUEUE_THRESHOLD_RATIO",
    defaults.ALERT_QUEUE_THRESHOLD_RATIO,
)
ALERT_DB_WRITE_P95_MS = _get_float("ALERT_DB_WRITE_P95_MS", defaults.ALERT_DB_WRITE_P95_MS)
ALERT_MEMORY_MB = _get_float("ALERT_MEMORY_MB", defaults.ALERT_MEMORY_MB)
ALERT_MEMORY_WINDOW_SECONDS = _get_int(
    "ALERT_MEMORY_WINDOW_SECONDS",
    defaults.ALERT_MEMORY_WINDOW_SECONDS,
)

SLO_BOT_RESPONSE_P95_MS = _get_float(
    "SLO_BOT_RESPONSE_P95_MS",
    defaults.SLO_BOT_RESPONSE_P95_MS,
)
SLO_QUEUE_WRITE_P95_MS = _get_float(
    "SLO_QUEUE_WRITE_P95_MS",
    defaults.SLO_QUEUE_WRITE_P95_MS,
)
SLO_DASHBOARD_QUERY_P95_MS = _get_float(
    "SLO_DASHBOARD_QUERY_P95_MS",
    defaults.SLO_DASHBOARD_QUERY_P95_MS,
)
SLO_MEMORY_P99_MB = _get_float("SLO_MEMORY_P99_MB", defaults.SLO_MEMORY_P99_MB)


# ──────────────────────────────────────────────
#  Fail-Fast: validate required configuration
# ──────────────────────────────────────────────

_PLACEHOLDER = "MISSING_TOKEN"


def _validate_config() -> None:
    """
    Validate all required environment variables at import time.
    Raises EnvironmentError immediately if anything critical is missing,
    so the process exits before attempting to connect to Telegram with bad
    credentials.  All existing module-level names remain unchanged.
    """
    errors: list[str] = []

    # Bot tokens must be present and must not be the placeholder default
    _token_vars = {
        "MAIN_BOT_TOKEN": MAIN_BOT_TOKEN,
        "ADMIN_BOT_TOKEN": ADMIN_BOT_TOKEN,
        "DEV_BOT_TOKEN": DEV_BOT_TOKEN,
    }
    for var_name, token in _token_vars.items():
        if not token or token == _PLACEHOLDER:
            errors.append(
                f"  • {var_name} is not set or still holds the placeholder value "
                f"'{_PLACEHOLDER}'. Add it to your .env file."
            )

    # ADMIN_IDS must contain at least one entry so the admin bot is accessible
    if not ADMIN_IDS:
        errors.append(
            "  • ADMIN_IDS is empty. Set it to a comma-separated list of "
            "Telegram user IDs that are allowed to access the admin bot "
            "(e.g. ADMIN_IDS=123456789)."
        )

    if errors:
        raise OSError(
            "\n\n🚨 Startup aborted — missing or invalid configuration:\n"
            + "\n".join(errors)
            + "\n\nFix the values in your .env file and restart the bot.\n"
        )


_validate_config()
