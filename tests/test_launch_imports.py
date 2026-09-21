import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("aiogram"), "requires installed runtime dependencies")
class LauncherImportTests(unittest.TestCase):
    def test_all_launchers_import_without_starting_network_polling(self):
        # Importing the runners exercises the platform-specific startup path.
        # Dummy values are enough because the test does not contact Telegram.
        script = """
import os

os.environ.update(
    BOT_ENV='test',
    MAIN_BOT_TOKEN='123456:dummy-main-token',
    ADMIN_BOT_TOKEN='123456:dummy-admin-token',
    DEV_BOT_TOKEN='123456:dummy-dev-token',
    ADMIN_IDS='123456',
)

import run_main
import run_dev
import run_admin
import run_admin_and_main
print('launchers imported')
"""
        project_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
