"""SQLite connection management, retries, and schema migrations."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

LOGGER = logging.getLogger(__name__)


class DatabaseError(RuntimeError):
    """Raised when the database cannot be initialized or queried safely."""


class Database:
    """Own a single aiosqlite connection and serialize write transactions."""

    def __init__(self, path: Path, migrations_dir: Path | None = None) -> None:
        self.path = path
        self.migrations_dir = migrations_dir or Path(__file__).resolve().parents[1] / "migrations"
        self._connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @property
    def connection(self) -> aiosqlite.Connection:
        """Return the open connection or fail clearly before initialization."""

        if self._connection is None:
            raise DatabaseError("Database connection has not been opened")
        return self._connection

    async def connect(self) -> None:
        """Open the database, configure SQLite, and apply pending migrations."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = await aiosqlite.connect(self.path, timeout=10.0)
            self._connection.row_factory = aiosqlite.Row
            await self._connection.execute("PRAGMA foreign_keys = ON")
            await self._connection.execute("PRAGMA journal_mode = WAL")
            await self._connection.execute("PRAGMA synchronous = NORMAL")
            await self._connection.execute("PRAGMA busy_timeout = 5000")
            await self._connection.commit()
            await self._apply_migrations()
        except (OSError, sqlite3.Error, aiosqlite.Error) as exc:
            await self.close()
            raise DatabaseError(f"Unable to initialize database at {self.path}: {exc}") from exc

    async def close(self) -> None:
        """Close the underlying connection if it is open."""

        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def _apply_migrations(self) -> None:
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        await self.connection.commit()

        rows = await self.fetchall("SELECT version FROM schema_migrations")
        applied = {int(row["version"]) for row in rows}
        migration_files = sorted(self.migrations_dir.glob("*.sql"))
        if not migration_files:
            raise DatabaseError(f"No migration files found in {self.migrations_dir}")

        for migration_file in migration_files:
            prefix = migration_file.name.split("_", maxsplit=1)[0]
            try:
                version = int(prefix)
            except ValueError as exc:
                raise DatabaseError(f"Invalid migration filename: {migration_file.name}") from exc
            if version in applied:
                continue
            sql = migration_file.read_text(encoding="utf-8")
            LOGGER.info("Applying database migration", extra={"migration": migration_file.name})
            safe_filename = migration_file.name.replace("'", "''")
            migration_script = (
                "BEGIN IMMEDIATE;\n"
                f"{sql}\n"
                "INSERT INTO schema_migrations(version, filename, applied_at) "
                f"VALUES ({version}, '{safe_filename}', "
                "strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'));\n"
                "COMMIT;"
            )
            async with self._write_lock:
                try:
                    await self.connection.executescript(migration_script)
                except BaseException:
                    await self.connection.rollback()
                    raise

    async def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        commit: bool = False,
        retries: int = 3,
    ) -> aiosqlite.Cursor:
        """Execute a parameterized statement with safe write transactions."""

        if not commit:
            return await self._execute_with_retries(sql, parameters, retries=retries)

        async with self._write_lock:
            await self._begin_immediate(retries=retries)
            try:
                cursor = await self.connection.execute(sql, parameters)
                await self.connection.commit()
                return cursor
            except BaseException:
                await self.connection.rollback()
                raise

    async def _begin_immediate(self, *, retries: int) -> None:
        """Acquire a SQLite write transaction before executing any mutation."""

        for attempt in range(retries):
            try:
                await self.connection.execute("BEGIN IMMEDIATE")
                return
            except (sqlite3.OperationalError, aiosqlite.OperationalError) as exc:
                if "locked" not in str(exc).lower() or attempt == retries - 1:
                    raise
                await asyncio.sleep(0.05 * (2**attempt))
        raise AssertionError("unreachable")

    async def _execute_with_retries(
        self,
        sql: str,
        parameters: tuple[Any, ...],
        *,
        retries: int,
    ) -> aiosqlite.Cursor:
        for attempt in range(retries):
            try:
                return await self.connection.execute(sql, parameters)
            except (sqlite3.OperationalError, aiosqlite.OperationalError) as exc:
                if "locked" not in str(exc).lower() or attempt == retries - 1:
                    raise
                await asyncio.sleep(0.05 * (2**attempt))
        raise AssertionError("unreachable")

    async def fetchone(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> aiosqlite.Row | None:
        """Fetch one row while serializing access to the shared connection."""

        async with self._write_lock:
            cursor = await self._execute_with_retries(sql, parameters, retries=3)
            try:
                return await cursor.fetchone()
            finally:
                await cursor.close()

    async def fetchall(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> list[aiosqlite.Row]:
        """Fetch all matching rows from the shared connection."""

        async with self._write_lock:
            cursor = await self._execute_with_retries(sql, parameters, retries=3)
            try:
                return list(await cursor.fetchall())
            finally:
                await cursor.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Run a serialized `BEGIN IMMEDIATE` transaction with lock retries."""

        async with self._write_lock:
            await self._begin_immediate(retries=3)
            try:
                yield self.connection
                await self.connection.commit()
            except BaseException:
                await self.connection.rollback()
                raise
