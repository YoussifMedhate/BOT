import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


# Allow the database layer to be tested with the standard library alone in a
# fresh checkout; CI also runs this test with the real python-dotenv package.
if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: False
    sys.modules["dotenv"] = dotenv_stub

os.environ.setdefault("MAIN_BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_BOT_TOKEN", "2:test")
os.environ.setdefault("DEV_BOT_TOKEN", "3:test")
os.environ.setdefault("ADMIN_IDS", "1")

from core.database import Database


class DatabaseBootstrapTests(unittest.TestCase):
    def test_empty_database_gets_a_main_menu(self):
        async def check() -> None:
            with tempfile.TemporaryDirectory() as directory:
                database = Database(str(Path(directory) / "bot.db"))
                await database.init_db()
                self.assertTrue(await database.menu_exists("main"))
                menu = await database.get_menu("main")
                self.assertIsNotNone(menu)
                self.assertEqual(menu["buttons"], [])
                await database.close()

        asyncio.run(check())
