from __future__ import annotations

from dataclasses import asdict

from config.settings import (
    SLO_BOT_RESPONSE_P95_MS,
    SLO_DASHBOARD_QUERY_P95_MS,
    SLO_MEMORY_P99_MB,
    SLO_QUEUE_WRITE_P95_MS,
)
from core.monitoring.metrics import metrics


def get_health_report() -> dict:
    snapshot = metrics.snapshot()
    memory_p99 = metrics.memory_p99_mb()
    violations = []

    if snapshot.bot_response_p95_ms > SLO_BOT_RESPONSE_P95_MS:
        violations.append("bot_response_p95")
    if snapshot.queue_write_p95_ms > SLO_QUEUE_WRITE_P95_MS:
        violations.append("queue_write_p95")
    if snapshot.dashboard_query_p95_ms > SLO_DASHBOARD_QUERY_P95_MS:
        violations.append("dashboard_query_p95")
    if memory_p99 > SLO_MEMORY_P99_MB:
        violations.append("memory_p99")

    report = asdict(snapshot)
    report["memory_p99_mb"] = memory_p99
    report["slo_violations"] = violations
    report["status"] = "degraded" if violations else "ok"
    return report
