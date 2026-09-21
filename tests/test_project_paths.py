import unittest
from pathlib import Path

from config import defaults


class ProjectPathTests(unittest.TestCase):
    def test_default_paths_are_absolute_project_paths(self):
        self.assertTrue(defaults.BASE_DIR.is_absolute())
        self.assertTrue(Path(defaults.DB_PATH).is_absolute())
        self.assertTrue(Path(defaults.ANALYTICS_DEAD_LETTER_PATH).is_absolute())
