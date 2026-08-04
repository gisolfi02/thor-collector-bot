from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.models import utc_now
from app.repositories.guild_repository import GuildRepository
from app.repositories.spawn_repository import SpawnRepository
from app.services.collectible_service import CollectibleService
from app.services.lock_registry import GuildLockRegistry
from app.services.spawn_manager import SpawnManager
from tests.conftest import seed_collectible, seed_guild


class FakeBot:
    def get_channel(self, channel_id: int):
        return None

    async def fetch_channel(self, channel_id: int):
        raise AssertionError("fetch_channel should not be reached while sleeping")


@pytest.mark.asyncio
async def test_restart_does_not_create_duplicate_tasks(database, tmp_path: Path) -> None:
    await seed_guild(database)
    blocker = asyncio.Event()

    async def controlled_sleep(seconds: float) -> None:
        await blocker.wait()

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text("[]", encoding="utf-8")
    manager = SpawnManager(
        FakeBot(),
        GuildRepository(database),
        SpawnRepository(database),
        CollectibleService(database, catalog_path, tmp_path),
        GuildLockRegistry(),
        sleep=controlled_sleep,
    )
    await manager.start_for_guild(1)
    first_task = manager.tasks[1]
    await asyncio.sleep(0)
    await manager.start_for_guild(1)
    second_task = manager.tasks[1]
    assert first_task is not second_task
    assert first_task.cancelled() or first_task.done()
    assert len(manager.tasks) == 1
    await manager.shutdown()


@pytest.mark.asyncio
async def test_database_rejects_two_active_spawns_for_same_guild(database) -> None:
    await seed_guild(database)
    await seed_collectible(database)
    repository = SpawnRepository(database)

    await repository.create_active(1, 10, 1000, "thor_001", utc_now())
    with pytest.raises(sqlite3.IntegrityError):
        await repository.create_active(1, 10, 1001, "thor_001", utc_now())
    assert await repository.count_active(1) == 1
