import pytest

from app.repositories.collection_repository import CollectionRepository
from tests.conftest import insert_captured_spawn, seed_collectible, seed_guild


@pytest.mark.asyncio
async def test_leaderboard_tiebreakers(database) -> None:
    await seed_guild(database)
    await seed_collectible(database, "thor_001")
    await seed_collectible(database, "thor_002")

    # User 200: two captures, two unique, first capture later.
    await insert_captured_spawn(
        database, guild_id=1, channel_id=10, user_id=200,
        collectible_id="thor_001", captured_offset_seconds=10,
    )
    await insert_captured_spawn(
        database, guild_id=1, channel_id=10, user_id=200,
        collectible_id="thor_002", captured_offset_seconds=11,
    )
    # User 201: two captures, one unique -> ranks below user 200.
    await insert_captured_spawn(
        database, guild_id=1, channel_id=10, user_id=201,
        collectible_id="thor_001", captured_offset_seconds=1,
    )
    await insert_captured_spawn(
        database, guild_id=1, channel_id=10, user_id=201,
        collectible_id="thor_001", captured_offset_seconds=2,
    )
    # Users 202 and 203: same totals/unique; earlier first capture wins.
    await insert_captured_spawn(
        database, guild_id=1, channel_id=10, user_id=202,
        collectible_id="thor_001", captured_offset_seconds=3,
    )
    await insert_captured_spawn(
        database, guild_id=1, channel_id=10, user_id=203,
        collectible_id="thor_001", captured_offset_seconds=4,
    )

    entries = await CollectionRepository(database).get_leaderboard(1)
    assert [entry.user_id for entry in entries] == [200, 201, 202, 203]
    assert [entry.rank for entry in entries] == [1, 2, 3, 4]
