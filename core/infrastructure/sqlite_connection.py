from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


async def _await_future(future) -> Any:
    """Wrap a concurrent.futures.Future into an awaitable via asyncio.wrap_future."""
    return await asyncio.wrap_future(future, loop=asyncio.get_running_loop())


class AsyncSQLiteCursor:
    def __init__(self, connection: AsyncSQLiteConnection, cursor: sqlite3.Cursor):
        self.connection = connection
        self.cursor = cursor

    async def fetchall(self) -> list[sqlite3.Row]:
        return await self.connection.run(self.cursor.fetchall)

    async def fetchone(self) -> sqlite3.Row | None:
        return await self.connection.run(self.cursor.fetchone)

    async def close(self) -> None:
        await self.connection.run(self.cursor.close)


class ExecuteContext:
    def __init__(
        self,
        connection: AsyncSQLiteConnection,
        sql: str,
        parameters: Iterable[Any],
    ):
        self.connection = connection
        self.sql = sql
        self.parameters = tuple(parameters)
        self.cursor: AsyncSQLiteCursor | None = None

    def __await__(self):
        return self.connection._execute(self.sql, self.parameters).__await__()

    async def __aenter__(self) -> AsyncSQLiteCursor:
        self.cursor = await self
        return self.cursor

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.cursor is not None:
            await self.cursor.close()


class AsyncSQLiteConnection:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite")
        self._conn: sqlite3.Connection | None = None
        self._row_factory: Callable | None = sqlite3.Row

    @property
    def row_factory(self) -> Callable | None:
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value: Callable | None) -> None:
        self._row_factory = value

    async def connect(self) -> AsyncSQLiteConnection:
        def open_connection() -> sqlite3.Connection:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = self._row_factory
            return conn

        self._conn = await _await_future(self._executor.submit(open_connection))
        return self

    async def run(self, fn: Callable, *args, **kwargs) -> Any:
        if self._conn is None:
            raise ValueError("Connection closed")

        def call() -> Any:
            if self._conn is None:
                raise RuntimeError("SQLite connection was closed before the task ran")
            self._conn.row_factory = self._row_factory
            return fn(*args, **kwargs)

        return await _await_future(self._executor.submit(call))

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> ExecuteContext:
        return ExecuteContext(self, sql, parameters)

    async def _execute(self, sql: str, parameters: Iterable[Any]) -> AsyncSQLiteCursor:
        def call() -> sqlite3.Cursor:
            if self._conn is None:
                raise RuntimeError("SQLite connection was closed before the task ran")
            self._conn.row_factory = self._row_factory
            return self._conn.execute(sql, tuple(parameters))

        cursor = await _await_future(self._executor.submit(call))
        return AsyncSQLiteCursor(self, cursor)

    async def executemany(self, sql: str, parameters: Iterable[Any]) -> AsyncSQLiteCursor:
        def call() -> sqlite3.Cursor:
            if self._conn is None:
                raise RuntimeError("SQLite connection was closed before the task ran")
            self._conn.row_factory = self._row_factory
            return self._conn.executemany(sql, parameters)

        cursor = await _await_future(self._executor.submit(call))
        return AsyncSQLiteCursor(self, cursor)

    async def commit(self) -> None:
        if self._conn is None:
            raise ValueError("Connection closed")
        await self.run(self._conn.commit)

    async def rollback(self) -> None:
        if self._conn is None:
            raise ValueError("Connection closed")
        await self.run(self._conn.rollback)

    async def close(self) -> None:
        if self._conn is None:
            return
        await self.run(self._conn.close)
        self._conn = None
        self._executor.shutdown(wait=True)


async def connect(db_path: str | Path) -> AsyncSQLiteConnection:
    return await AsyncSQLiteConnection(db_path).connect()
