import unittest
from unittest.mock import patch

from core import platform_compat


class PlatformCompatibilityTests(unittest.TestCase):
    def test_windows_keeps_the_default_event_loop_policy(self):
        with patch.object(platform_compat.sys, "platform", "win32"):
            self.assertFalse(platform_compat.configure_event_loop_policy())
