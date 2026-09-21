from pathlib import Path

# Keep project-owned paths independent of the directory from which Python was
# launched.  Path handles the native separator on both Windows and Linux.
BASE_DIR = Path(__file__).resolve().parent.parent

BOT_ENV = "dev"
DB_PATH = str(BASE_DIR / "config" / "bot_structure.db")

BACKUP_INTERVAL_HOURS = 6
BACKUP_RETENTION_DAILY = 7
BACKUP_RETENTION_WEEKLY = 4
BACKUP_RETENTION_MONTHLY = 12

ANALYTICS_QUEUE_MAX_SIZE = 1000
ANALYTICS_FLUSH_INTERVAL_SECONDS = 5.0
ANALYTICS_BATCH_SIZE = 100
ANALYTICS_DEAD_LETTER_PATH = str(BASE_DIR / "logs" / "analytics_dead_letters.jsonl")

RATE_LIMIT_WINDOW_SECONDS = 1.0
RATE_LIMIT_MAX_EVENTS = 8

ALERT_QUEUE_THRESHOLD_RATIO = 0.8
ALERT_DB_WRITE_P95_MS = 100.0
ALERT_MEMORY_MB = 200.0
ALERT_MEMORY_WINDOW_SECONDS = 300

SLO_BOT_RESPONSE_P95_MS = 100.0
SLO_QUEUE_WRITE_P95_MS = 20.0
SLO_DASHBOARD_QUERY_P95_MS = 300.0
SLO_MEMORY_P99_MB = 250.0
