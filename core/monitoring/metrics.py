from __future__ import annotations

import os
import sys
import threading
from collections import deque
from dataclasses import dataclass

try:
    # ``resource`` is a POSIX-only module.  Importing it unconditionally makes
    # the whole application fail to start on Windows before the psutil path
    # below gets a chance to run.
    import resource as _resource
except ImportError:  # pragma: no cover - exercised on Windows
    _resource = None


class RollingValues:
    def __init__(self, maxlen: int = 1000):
        self._values: deque[float] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, value: float) -> None:
        with self._lock:
            self._values.append(float(value))

    def percentile(self, percentile: float) -> float:
        with self._lock:
            values = sorted(self._values)
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        index = (len(values) - 1) * (percentile / 100)
        lower = int(index)
        upper = min(lower + 1, len(values) - 1)
        weight = index - lower
        return values[lower] * (1 - weight) + values[upper] * weight

    def count(self) -> int:
        with self._lock:
            return len(self._values)


@dataclass(frozen=True)
class MetricsSnapshot:
    bot_response_p95_ms: float
    queue_write_p95_ms: float
    dashboard_query_p95_ms: float
    memory_mb: float
    queue_length: int
    samples: dict[str, int]


class AppMetrics:
    def __init__(self) -> None:
        self.bot_response_ms = RollingValues()
        self.queue_write_ms = RollingValues()
        self.dashboard_query_ms = RollingValues()
        self.memory_mb_values = RollingValues()
        self._queue_length = 0
        self._lock = threading.Lock()

    def record_bot_response_ms(self, value: float) -> None:
        self.bot_response_ms.add(value)

    def record_queue_write_ms(self, value: float) -> None:
        self.queue_write_ms.add(value)

    def record_dashboard_query_ms(self, value: float) -> None:
        self.dashboard_query_ms.add(value)

    def set_queue_length(self, value: int) -> None:
        with self._lock:
            self._queue_length = max(0, value)

    def record_memory_mb(self, value: float | None = None) -> float:
        memory = value if value is not None else get_process_memory_mb()
        self.memory_mb_values.add(memory)
        return memory

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            queue_length = self._queue_length
        memory = self.record_memory_mb()
        return MetricsSnapshot(
            bot_response_p95_ms=self.bot_response_ms.percentile(95),
            queue_write_p95_ms=self.queue_write_ms.percentile(95),
            dashboard_query_p95_ms=self.dashboard_query_ms.percentile(95),
            memory_mb=memory,
            queue_length=queue_length,
            samples={
                "bot_response": self.bot_response_ms.count(),
                "queue_write": self.queue_write_ms.count(),
                "dashboard_query": self.dashboard_query_ms.count(),
                "memory": self.memory_mb_values.count(),
            },
        )

    def memory_p99_mb(self) -> float:
        return self.memory_mb_values.percentile(99)


def get_process_memory_mb() -> float:
    """Return the current process RSS in MiB on every supported platform.

    ``psutil`` is an explicit dependency and provides the same RSS value on
    Windows and Linux.  The POSIX fallback keeps metrics useful if that
    optional import fails, without importing POSIX-only modules on Windows.
    """
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        if _resource is None:
            # A missing psutil installation should not prevent the bot from
            # starting on Windows.  It simply disables memory-based alerts.
            return 0.0

        usage = _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return usage / (1024 * 1024)
        return usage / 1024


metrics = AppMetrics()
