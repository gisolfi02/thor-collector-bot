import pytest

from app.repositories.guild_repository import GuildRepository
from tests.conftest import insert_captured_spawn, seed_collectible, seed_guild


@pytest.mark.asyncio
async def test_destroy_deletes_only_target_guild(database) -> None:
    await seed_guild(database, guild_id=1, channel_id=10, admin_id=100)
    await seed_guild(database, guild_id=2, channel_id=20, admin_id=200)
    await seed_collectible(database, "thor_001")
    await insert_captured_spawn(
        database,
        guild_id=1,
        channel_id=10,
        user_id=101,
        collectible_id="thor_001",
        captured_offset_seconds=1,
    )
    await insert_captured_spawn(
        database,
        guild_id=2,
        channel_id=20,
        user_id=201,
        collectible_id="thor_001",
        captured_offset_seconds=2,
    )
    now = "2026-08-04T09:00:00.000000Z"
    for guild_id, user_id in ((1, 101), (2, 201)):
        await database.execute(
            """
            INSERT INTO user_collections(
                guild_id, user_id, collectible_id, quantity,
                first_captured_at, last_captured_at
            ) VALUES (?, ?, 'thor_001', 1, ?, ?)
            """,
            (guild_id, user_id, now, now),
            commit=True,
        )

    repo = GuildRepository(database)
    await repo.destroy(1)

    assert await repo.get(1) is None
    assert await repo.get(2) is not None
    row1 = await database.fetchone("SELECT COUNT(*) AS count FROM captures WHERE guild_id = 1")
    row2 = await database.fetchone("SELECT COUNT(*) AS count FROM captures WHERE guild_id = 2")
    collection1 = await database.fetchone(
        "SELECT COUNT(*) AS count FROM user_collections WHERE guild_id = 1"
    )
    collection2 = await database.fetchone(
        "SELECT COUNT(*) AS count FROM user_collections WHERE guild_id = 2"
    )
    assert int(row1["count"]) == 0
    assert int(row2["count"]) == 1
    assert int(collection1["count"]) == 0
    assert int(collection2["count"]) == 1


@pytest.mark.asyncio
async def test_first_start_assigns_first_admin(database) -> None:
    repo = GuildRepository(database)
    config = await repo.create_or_reactivate(123, 456, 789, 30, 90)
    assert config.game_admin_user_id == 789
    assert config.channel_id == 456
    assert config.is_active
