from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest_asyncio

from app.database import Database
from app.models import to_utc_iso, utc_now
from app.repositories.guild_repository import GuildRepository
from app.repositories.spawn_repository import SpawnRepository


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(tmp_path / "test.sqlite3")
    await db.connect()
    try:
        yield db
    finally:
        await db.close()


async def seed_collectible(database: Database, collectible_id: str = "thor_001") -> None:
    await database.execute(
        """
        INSERT OR REPLACE INTO collectibles(
            collectible_id, name, filename, caption, description, rarity, is_enabled
        ) VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (
            collectible_id,
            f"Thor {collectible_id}",
            f"{collectible_id}.jpg",
            "Un nuovo Thor è apparso!",
            "Descrizione di test",
            "Comune",
        ),
        commit=True,
    )


async def seed_guild(
    database: Database, guild_id: int = 1, channel_id: int = 10, admin_id: int = 100
):
    repo = GuildRepository(database)
    return await repo.create_or_reactivate(guild_id, channel_id, admin_id, 30, 90)


async def seed_active_spawn(
    database: Database,
    guild_id: int = 1,
    channel_id: int = 10,
    collectible_id: str = "thor_001",
    message_id: int = 999,
):
    await seed_collectible(database, collectible_id)
    spawn_repo = SpawnRepository(database)
    spawned_at = utc_now() - timedelta(seconds=1)
    spawn_id = await spawn_repo.create_active(
        guild_id, channel_id, message_id, collectible_id, spawned_at
    )
    return spawn_id, spawned_at


async def insert_captured_spawn(
    database: Database,
    *,
    guild_id: int,
    channel_id: int,
    user_id: int,
    collectible_id: str,
    captured_offset_seconds: int,
) -> None:
    now = utc_now() + timedelta(seconds=captured_offset_seconds)
    cursor = await database.execute(
        """
        INSERT INTO spawns(
            guild_id, channel_id, message_id, collectible_id, status,
            spawned_at, captured_at, captured_by_user_id
        ) VALUES (?, ?, ?, ?, 'CAPTURED', ?, ?, ?)
        """,
        (
            guild_id,
            channel_id,
            100_000 + captured_offset_seconds + user_id,
            collectible_id,
            to_utc_iso(now - timedelta(seconds=1)),
            to_utc_iso(now),
            user_id,
        ),
        commit=True,
    )
    await database.execute(
        """
        INSERT INTO captures(
            guild_id, user_id, collectible_id, spawn_id, captured_at, capture_time_ms
        ) VALUES (?, ?, ?, ?, ?, 1000)
        """,
        (guild_id, user_id, collectible_id, int(cursor.lastrowid), to_utc_iso(now)),
        commit=True,
    )
