import asyncio
import json
import logging
import sqlite3
from pathlib import Path

from config.settings import DB_PATH
from core.infrastructure.sqlite_connection import AsyncSQLiteConnection, connect
from core.migrations.runner import apply_migrations


logger = logging.getLogger(__name__)

_MAIN_MENU_NAME = "main"
_DEFAULT_MAIN_MENU_TEXT = "القائمة الرئيسية"


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: AsyncSQLiteConnection | None = None
        self._write_lock = asyncio.Lock()

    # ──────────────────────────────────────────────
    #  Connection & Initialization
    # ──────────────────────────────────────────────

    async def _get_conn(self) -> AsyncSQLiteConnection:
        """Return the persistent connection, opening it if needed."""
        if self._conn is None:
            Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            self._conn = await connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    async def init_db(self) -> None:
        """Create tables, indexes, and run migrations on a persistent connection."""
        conn = await self._get_conn()

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS menus (
                name    TEXT PRIMARY KEY,
                parent  TEXT,
                text    TEXT NOT NULL,
                buttons TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY (parent) REFERENCES menus(name)
            )
        """)
        await self._ensure_main_menu(conn)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS materials (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                menu_name   TEXT NOT NULL,
                channel_id  TEXT NOT NULL,
                message_id  INTEGER NOT NULL,
                description TEXT,
                order_index INTEGER NOT NULL DEFAULT 0,
                file_id     TEXT,
                file_type   TEXT,
                FOREIGN KEY (menu_name) REFERENCES menus(name) ON DELETE CASCADE
            )
        """)

        # Migration: add file_id and file_type columns if they don't exist
        try:
            await conn.execute("ALTER TABLE materials ADD COLUMN file_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE materials ADD COLUMN file_type TEXT")
        except sqlite3.OperationalError:
            pass

        # CR-11: index on materials.menu_name for faster lookups
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_materials_menu ON materials(menu_name)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_materials_menu_order ON materials(menu_name, order_index)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_menus_parent ON menus(parent)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_buttons (
                button_name TEXT PRIMARY KEY,
                menu_name TEXT,
                description TEXT,
                status TEXT DEFAULT 'pending',
                row_index INTEGER,
                position_index INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._ensure_custom_buttons_schema(conn)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_custom_buttons_status ON custom_buttons(status)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_custom_buttons_menu ON custom_buttons(menu_name)"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                root_menu TEXT NOT NULL DEFAULT 'main',
                permissions TEXT NOT NULL DEFAULT '[]',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (root_menu) REFERENCES menus(name) ON DELETE SET DEFAULT
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_users_active ON admin_users(is_active)"
        )
        await apply_migrations(conn)
        await conn.commit()

    async def _ensure_main_menu(self, conn: AsyncSQLiteConnection) -> None:
        """Create a safe root menu for a brand-new or incomplete database.

        Production containers commonly start with an empty mounted SQLite file.
        The main bot always opens the ``main`` menu, so leaving it absent turns
        the first user update into a KeyError.  Existing content is never
        changed because INSERT OR IGNORE only acts when the row is missing.
        """
        async with conn.execute(
            "SELECT 1 FROM menus WHERE name = ?", (_MAIN_MENU_NAME,)
        ) as cursor:
            exists = await cursor.fetchone()

        if exists is not None:
            return

        await conn.execute(
            """
            INSERT OR IGNORE INTO menus (name, parent, text, buttons)
            VALUES (?, NULL, ?, ?)
            """,
            (_MAIN_MENU_NAME, _DEFAULT_MAIN_MENU_TEXT, "[]"),
        )
        logger.warning(
            "The main menu was missing; created an empty default menu. "
            "Restore the production database or configure persistent storage.",
            extra={"event": "main_menu_bootstrapped"},
        )

    async def _ensure_custom_buttons_schema(self, conn: AsyncSQLiteConnection) -> None:
        """Bring older custom_buttons tables up to the current shape."""
        async with conn.execute("PRAGMA table_info(custom_buttons)") as cursor:
            rows = await cursor.fetchall()

        existing_columns = {row["name"] for row in rows}
        column_defs = {
            "menu_name": "TEXT",
            "row_index": "INTEGER",
            "position_index": "INTEGER",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        }

        for column, definition in column_defs.items():
            if column not in existing_columns:
                await conn.execute(f"ALTER TABLE custom_buttons ADD COLUMN {column} {definition}")
                existing_columns.add(column)

        await conn.execute(
            """
            UPDATE custom_buttons
            SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
                updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
            """
        )
        await self._backfill_custom_button_locations(conn)

    async def _backfill_custom_button_locations(self, conn: AsyncSQLiteConnection) -> None:
        """Fill missing custom button locations from the menu button JSON."""
        async with conn.execute(
            "SELECT button_name FROM custom_buttons WHERE menu_name IS NULL"
        ) as cursor:
            custom_rows = await cursor.fetchall()
        if not custom_rows:
            return

        pending_names = {row["button_name"] for row in custom_rows}
        locations: dict[str, tuple[str, int, int]] = {}

        async with conn.execute("SELECT name, buttons FROM menus") as cursor:
            menu_rows = await cursor.fetchall()

        for menu_row in menu_rows:
            try:
                buttons = json.loads(menu_row["buttons"] or "[]")
            except json.JSONDecodeError:
                continue
            for row_index, button_row in enumerate(buttons):
                for position_index, button_name in enumerate(button_row):
                    if button_name in pending_names and button_name not in locations:
                        locations[button_name] = (
                            menu_row["name"],
                            row_index,
                            position_index,
                        )

        for button_name, (menu_name, row_index, position_index) in locations.items():
            await conn.execute(
                """
                UPDATE custom_buttons
                SET menu_name = ?,
                    row_index = ?,
                    position_index = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE button_name = ?
                """,
                (menu_name, row_index, position_index, button_name),
            )

    async def close(self) -> None:
        """Gracefully close the persistent connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ──────────────────────────────────────────────
    #  Public interface for infrastructure layer
    # ──────────────────────────────────────────────

    @property
    def write_lock(self) -> asyncio.Lock:
        """The write lock used to serialise all write operations."""
        return self._write_lock

    async def get_connection(self):
        """Return the persistent connection, opening it if needed."""
        return await self._get_conn()

    async def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute a SELECT and return all rows."""
        return await self._fetchall(sql, params)

    async def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """Execute a SELECT and return a single row or None."""
        return await self._fetchone(sql, params)

    # ──────────────────────────────────────────────
    #  DRY Helpers
    # ──────────────────────────────────────────────

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute a SELECT and return all rows."""
        conn = await self._get_conn()
        async with conn.execute(sql, params) as cursor:
            return await cursor.fetchall()

    async def _fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """Execute a SELECT and return a single row or None."""
        conn = await self._get_conn()
        async with conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def _execute(self, sql: str, params: tuple = ()) -> None:
        """Execute a single write statement under the write lock and commit."""
        async with self._write_lock:
            conn = await self._get_conn()
            await conn.execute(sql, params)
            await conn.commit()

    async def _executemany(self, sql: str, params: list[tuple]) -> None:
        """Execute a batch of write statements in a single transaction."""
        if not params:
            return
        async with self._write_lock:
            conn = await self._get_conn()
            await conn.executemany(sql, params)
            await conn.commit()

    async def _execute_transaction(self, statements: list[tuple[str, tuple]]) -> None:
        """
        Execute multiple (sql, params) pairs in a single BEGIN/COMMIT block.

        This replaces the pattern of chaining several _execute() calls — each
        of which opens its own transaction — with one atomic transaction that
        cuts N commits down to 1 and guarantees all-or-nothing semantics across
        the entire group of statements.

        Args:
            statements: Ordered list of (sql, params) tuples to execute.
        """
        if not statements:
            return
        async with self._write_lock:
            conn = await self._get_conn()
            try:
                for sql, params in statements:
                    await conn.execute(sql, params)
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    # ──────────────────────────────────────────────
    #  Read Operations
    # ──────────────────────────────────────────────

    async def get_all_menus(self) -> dict:
        """Read all menus and return them as a dict."""
        rows = await self._fetchall("SELECT name, parent, text, buttons FROM menus")
        result = {}
        for row in rows:
            result[row["name"]] = {
                "parent": row["parent"],
                "text": row["text"],
                "buttons": json.loads(row["buttons"]),
            }
        return result

    async def get_menu(self, name: str) -> dict | None:
        """Read a single menu's details. Returns {parent, text, buttons}."""
        row = await self._fetchone(
            "SELECT parent, text, buttons FROM menus WHERE name = ?", (name,)
        )
        if row is None:
            return None
        return {
            "parent": row["parent"],
            "text": row["text"],
            "buttons": json.loads(row["buttons"]),
        }

    async def menu_exists(self, name: str) -> bool:
        """Check if a menu exists."""
        row = await self._fetchone("SELECT 1 FROM menus WHERE name = ?", (name,))
        return row is not None

    async def get_children(self, name: str) -> list:
        """Get direct children of a menu."""
        rows = await self._fetchall("SELECT name FROM menus WHERE parent = ?", (name,))
        return [row["name"] for row in rows]

    async def list_menu_names(self) -> list:
        """List all menu names."""
        rows = await self._fetchall("SELECT name FROM menus")
        return [row["name"] for row in rows]

    async def get_menu_buttons(self, name: str) -> list:
        """Get a menu's buttons as a list of lists."""
        row = await self._fetchone("SELECT buttons FROM menus WHERE name = ?", (name,))
        if row is None:
            return []
        return json.loads(row["buttons"])

    # ──────────────────────────────────────────────
    #  Write Operations
    # ──────────────────────────────────────────────

    async def upsert_menu(self, name: str, parent: str | None, text: str, buttons: list) -> None:
        """Insert or replace a menu."""
        await self._execute(
            """
            INSERT INTO menus (name, parent, text, buttons)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                parent  = excluded.parent,
                text    = excluded.text,
                buttons = excluded.buttons
            """,
            (name, parent, text, json.dumps(buttons, ensure_ascii=False)),
        )

    async def delete_menu_from_db(self, name: str) -> None:
        """Delete a menu from the database."""
        await self._execute("DELETE FROM menus WHERE name = ?", (name,))

    async def update_menu_field(self, name: str, field: str, value) -> None:
        """
        Update a single field of a menu.
        field must be one of: parent, text, buttons.
        """
        allowed = {"parent", "text", "buttons"}
        if field not in allowed:
            raise ValueError(f"Field must be one of {allowed}")

        if field == "buttons":
            value = json.dumps(value, ensure_ascii=False)

        await self._execute(
            f"UPDATE menus SET {field} = ? WHERE name = ?",
            (value, name),
        )

    async def rename_menu_in_db(self, old_name: str, new_name: str) -> None:
        """
        Rename a menu: update its name and update all children's parent references,
        and update the button text in the parent menu.
        All operations are performed in a single atomic transaction under the write
        lock. BEGIN IMMEDIATE is used so that SQLite acquires an exclusive write
        lock *before* any reads take place, eliminating the TOCTOU race condition
        that existed when reads were performed via _fetchone() outside a transaction.
        """
        if old_name == new_name:
            return

        async with self._write_lock:
            conn = await self._get_conn()

            try:
                # BEGIN IMMEDIATE acquires a reserved (write-intent) lock on the
                # database file immediately, preventing any concurrent writer from
                # modifying rows between our reads and our writes.
                await conn.execute("BEGIN IMMEDIATE")

                # --- Read: fetch the menu being renamed ---
                async with conn.execute(
                    "SELECT parent, text, buttons FROM menus WHERE name = ?",
                    (old_name,),
                ) as cursor:
                    row = await cursor.fetchone()

                if row is None:
                    await conn.rollback()
                    raise ValueError(f"Menu '{old_name}' not found")

                parent = row["parent"]
                text = row["text"]
                buttons = json.loads(row["buttons"])

                # Insert the new menu entry
                await conn.execute(
                    "INSERT INTO menus (name, parent, text, buttons) VALUES (?, ?, ?, ?)",
                    (new_name, parent, text, json.dumps(buttons, ensure_ascii=False)),
                )

                # Re-parent children
                await conn.execute(
                    "UPDATE menus SET parent = ? WHERE parent = ?",
                    (new_name, old_name),
                )

                # --- Read: fetch parent's button list and patch it ---
                if parent:
                    async with conn.execute(
                        "SELECT buttons FROM menus WHERE name = ?", (parent,)
                    ) as cursor:
                        parent_row = await cursor.fetchone()

                    if parent_row:
                        parent_buttons = json.loads(parent_row["buttons"])
                        for r in parent_buttons:
                            for i, btn in enumerate(r):
                                if btn == old_name:
                                    r[i] = new_name
                        await conn.execute(
                            "UPDATE menus SET buttons = ? WHERE name = ?",
                            (json.dumps(parent_buttons, ensure_ascii=False), parent),
                        )

                # Update materials referencing the old menu name
                await conn.execute(
                    "UPDATE materials SET menu_name = ? WHERE menu_name = ?",
                    (new_name, old_name),
                )

                # Keep supervisor scopes attached to the renamed menu.
                await conn.execute(
                    "UPDATE admin_users SET root_menu = ? WHERE root_menu = ?",
                    (new_name, old_name),
                )

                # Remove the old menu entry
                await conn.execute("DELETE FROM menus WHERE name = ?", (old_name,))

                # Single atomic commit for the entire rename
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                raise e

    # ──────────────────────────────────────────────
    #  Materials Operations
    # ──────────────────────────────────────────────

    async def add_material(
        self,
        menu_name: str,
        channel_id: str,
        message_id: int,
        description: str | None = None,
        order_index: int = 0,
        file_id: str | None = None,
        file_type: str | None = None,
    ) -> None:
        """Add a material to a menu."""
        await self._execute(
            """
            INSERT INTO materials (menu_name, channel_id, message_id, description, order_index, file_id, file_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (menu_name, channel_id, message_id, description, order_index, file_id, file_type),
        )

    async def add_materials(self, materials: list[tuple]) -> None:
        """Add multiple materials in a single transaction."""
        await self._executemany(
            """
            INSERT INTO materials (menu_name, channel_id, message_id, description, order_index, file_id, file_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            materials,
        )

    async def remove_material(self, material_id: int) -> None:
        """Remove a material by ID."""
        await self._execute("DELETE FROM materials WHERE id = ?", (material_id,))

    async def get_materials(self, menu_name: str) -> list:
        """Get all materials for a specific menu."""
        rows = await self._fetchall(
            "SELECT id, menu_name, channel_id, message_id, description, order_index, file_id, file_type "
            "FROM materials WHERE menu_name = ? ORDER BY order_index",
            (menu_name,),
        )
        return [dict(row) for row in rows]

    async def get_all_materials(self) -> dict:
        """Get all materials grouped by menu_name."""
        rows = await self._fetchall(
            "SELECT id, menu_name, channel_id, message_id, description, order_index, file_id, file_type "
            "FROM materials ORDER BY order_index"
        )
        result: dict[str, list[dict]] = {}
        for row in rows:
            mn = row["menu_name"]
            if mn not in result:
                result[mn] = []
            result[mn].append(dict(row))
        return result

    async def get_material_by_id(self, material_id: int) -> dict | None:
        """Get a single material by ID (CR-12: includes file_id and file_type)."""
        row = await self._fetchone(
            "SELECT id, menu_name, channel_id, message_id, description, order_index, file_id, file_type "
            "FROM materials WHERE id = ?",
            (material_id,),
        )
        if row is None:
            return None
        return dict(row)

    async def count_materials(self, menu_name: str) -> int:
        """Count the number of materials for a specific menu."""
        row = await self._fetchone(
            "SELECT COUNT(*) as count FROM materials WHERE menu_name = ?",
            (menu_name,),
        )
        if row is None:
            raise RuntimeError(f"COUNT(*) returned no row for menu '{menu_name}'")
        return row["count"]

    async def swap_materials(self, mat_id_1: int, mat_id_2: int) -> None:
        """Swap the order_index of two materials atomically."""
        async with self._write_lock:
            conn = await self._get_conn()
            try:
                # BEGIN IMMEDIATE locks the DB before any read so both SELECTs
                # and both UPDATEs happen in the same serializable snapshot.
                await conn.execute("BEGIN IMMEDIATE")

                async with conn.execute(
                    "SELECT order_index FROM materials WHERE id = ?", (mat_id_1,)
                ) as cursor:
                    mat1 = await cursor.fetchone()
                async with conn.execute(
                    "SELECT order_index FROM materials WHERE id = ?", (mat_id_2,)
                ) as cursor:
                    mat2 = await cursor.fetchone()

                if mat1 and mat2:
                    await conn.execute(
                        "UPDATE materials SET order_index = ? WHERE id = ?",
                        (mat2["order_index"], mat_id_1),
                    )
                    await conn.execute(
                        "UPDATE materials SET order_index = ? WHERE id = ?",
                        (mat1["order_index"], mat_id_2),
                    )
                    await conn.commit()
                else:
                    await conn.rollback()
            except Exception as e:
                await conn.rollback()
                raise e

    # ──────────────────────────────────────────────
    #  Users Operations
    # ──────────────────────────────────────────────

    async def add_user(self, user_id: int, username: str, full_name: str) -> None:
        """Add or update a user."""
        await self._execute(
            """
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name
            """,
            (user_id, username, full_name),
        )

    async def get_all_users(self) -> list:
        """Get all user IDs."""
        rows = await self._fetchall("SELECT user_id FROM users")
        return [row[0] for row in rows]

    async def count_users(self) -> int:
        """Count registered users without loading all IDs."""
        row = await self._fetchone("SELECT COUNT(*) as count FROM users")
        if row is None:
            raise RuntimeError("COUNT(*) on users returned no row")
        return row["count"]

    async def iter_user_ids(self, batch_size: int = 500):
        """Yield user IDs in primary-key order without loading the full table."""
        last_id = -1
        while True:
            rows = await self._fetchall(
                """
                SELECT user_id FROM users
                WHERE user_id > ?
                ORDER BY user_id
                LIMIT ?
                """,
                (last_id, batch_size),
            )
            if not rows:
                break
            for row in rows:
                last_id = row["user_id"]
                yield row["user_id"]

    # ──────────────────────────────────────────────
    #  Custom Buttons Operations
    # ──────────────────────────────────────────────

    async def add_custom_button(
        self,
        button_name: str,
        description: str,
        menu_name: str | None = None,
        row_index: int | None = None,
        position_index: int | None = None,
    ) -> None:
        """Add a new custom button request to the database."""
        await self._execute(
            """
            INSERT INTO custom_buttons (
                button_name, menu_name, description, status,
                row_index, position_index, created_at, updated_at
            )
            VALUES (?, ?, ?, 'pending', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(button_name) DO UPDATE SET
                menu_name = excluded.menu_name,
                description = excluded.description,
                status = 'pending',
                row_index = excluded.row_index,
                position_index = excluded.position_index,
                updated_at = CURRENT_TIMESTAMP
            """,
            (button_name, menu_name, description, row_index, position_index),
        )

    async def is_custom_button_pending(self, button_name: str) -> bool:
        """Check if a button text exists as a custom button (pending)."""
        row = await self._fetchone(
            "SELECT 1 FROM custom_buttons WHERE button_name = ? AND status = 'pending'",
            (button_name,),
        )
        return row is not None

    async def get_pending_buttons(self) -> list:
        """Get all custom button requests with 'pending' status."""
        rows = await self._fetchall(
            """
            SELECT button_name, menu_name, description, row_index, position_index
            FROM custom_buttons
            WHERE status = 'pending'
            ORDER BY created_at, button_name
            """
        )
        return [dict(row) for row in rows]

    async def mark_button_done(self, button_name: str) -> None:
        """Mark a custom button request as completed."""
        await self._execute(
            """
            UPDATE custom_buttons
            SET status = 'completed', updated_at = CURRENT_TIMESTAMP
            WHERE button_name = ?
            """,
            (button_name,),
        )

    async def delete_custom_button(self, button_name: str) -> None:
        """Delete a custom button request by its button text."""
        await self._execute(
            "DELETE FROM custom_buttons WHERE button_name = ?",
            (button_name,),
        )

    async def sync_custom_button_locations_for_menu(self, menu_name: str) -> None:
        """Refresh custom button row/position metadata for one menu."""
        buttons = await self.get_menu_buttons(menu_name)
        locations = [
            (menu_name, row_index, position_index, button_name)
            for row_index, button_row in enumerate(buttons)
            for position_index, button_name in enumerate(button_row)
        ]

        async with self._write_lock:
            conn = await self._get_conn()
            try:
                await conn.execute(
                    """
                    UPDATE custom_buttons
                    SET menu_name = NULL,
                        row_index = NULL,
                        position_index = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE menu_name = ?
                    """,
                    (menu_name,),
                )
                for location in locations:
                    await conn.execute(
                        """
                        UPDATE custom_buttons
                        SET menu_name = ?,
                            row_index = ?,
                            position_index = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE button_name = ?
                        """,
                        location,
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    # ──────────────────────────────────────────────
    #  Admin Users & Permissions
    # ──────────────────────────────────────────────

    async def get_admin_user(self, user_id: int) -> dict | None:
        """Get a supervisor admin by Telegram user ID."""
        row = await self._fetchone(
            """
            SELECT user_id, name, root_menu, permissions, is_active, created_at, updated_at
            FROM admin_users
            WHERE user_id = ?
            """,
            (user_id,),
        )
        if row is None:
            return None
        result = dict(row)
        result["permissions"] = json.loads(result["permissions"] or "[]")
        result["is_active"] = bool(result["is_active"])
        return result

    async def list_admin_users(self) -> list[dict]:
        """List all supervisor admins."""
        rows = await self._fetchall(
            """
            SELECT user_id, name, root_menu, permissions, is_active, created_at, updated_at
            FROM admin_users
            ORDER BY is_active DESC, user_id
            """
        )
        result = []
        for row in rows:
            item = dict(row)
            item["permissions"] = json.loads(item["permissions"] or "[]")
            item["is_active"] = bool(item["is_active"])
            result.append(item)
        return result

    async def upsert_admin_user(
        self,
        user_id: int,
        name: str | None = None,
        root_menu: str = "main",
        permissions: list[str] | None = None,
        is_active: bool = True,
    ) -> None:
        """Create or update a supervisor admin."""
        await self._execute(
            """
            INSERT INTO admin_users (user_id, name, root_menu, permissions, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                root_menu = excluded.root_menu,
                permissions = excluded.permissions,
                is_active = excluded.is_active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                name,
                root_menu,
                json.dumps(permissions or [], ensure_ascii=False),
                1 if is_active else 0,
            ),
        )

    async def set_admin_permissions(self, user_id: int, permissions: list[str]) -> None:
        """Replace a supervisor admin's permission list."""
        await self._execute(
            """
            UPDATE admin_users
            SET permissions = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (json.dumps(permissions, ensure_ascii=False), user_id),
        )

    async def set_admin_root_menu(self, user_id: int, root_menu: str) -> None:
        """Set the menu subtree a supervisor admin can manage."""
        await self._execute(
            """
            UPDATE admin_users
            SET root_menu = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (root_menu, user_id),
        )

    async def set_admin_active(self, user_id: int, is_active: bool) -> None:
        """Activate or deactivate a supervisor admin."""
        await self._execute(
            """
            UPDATE admin_users
            SET is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (1 if is_active else 0, user_id),
        )

    async def delete_admin_user(self, user_id: int) -> None:
        """Remove a supervisor admin completely."""
        await self._execute("DELETE FROM admin_users WHERE user_id = ?", (user_id,))


# Singleton instance
db = Database(DB_PATH)
