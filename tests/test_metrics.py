import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

from core.monitoring import metrics as metrics_module


class _FakeProcess:
    def memory_info(self):
        return type("MemoryInfo", (), {"rss": 12 * 1024 * 1024})()


class _FakePsutil:
    @staticmethod
    def Process(_pid):
        return _FakeProcess()


class MetricsCompatibilityTests(unittest.TestCase):
    def test_module_imports_when_posix_resource_is_unavailable(self):
        # Run in a fresh interpreter so Linux's resource module can be hidden
        # without mutating the test runner. This reproduces the Windows import
        # condition that previously prevented every launcher from starting.
        script = """
import builtins

original_import = builtins.__import__

def import_without_resource(name, *args, **kwargs):
    if name == 'resource':
        raise ImportError('resource is unavailable')
    return original_import(name, *args, **kwargs)

builtins.__import__ = import_without_resource
import core.monitoring.metrics as metrics
assert metrics._resource is None
"""
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_memory_uses_psutil_on_all_platforms(self):
        with patch.dict(sys.modules, {"psutil": _FakePsutil}):
            self.assertEqual(metrics_module.get_process_memory_mb(), 12.0)

    def test_memory_fallback_is_safe_without_posix_resource(self):
        # This is the Windows path when psutil cannot be imported.
        with patch.dict(sys.modules, {"psutil": None}):
            with patch.object(metrics_module, "_resource", None):
                self.assertEqual(metrics_module.get_process_memory_mb(), 0.0)
