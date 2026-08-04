from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.models import CaptureAttempt, utc_now
from app.services.capture_service import CaptureService
from app.services.lock_registry import GuildLockRegistry
from tests.conftest import seed_active_spawn, seed_guild


@pytest.mark.asyncio
async def test_wrong_channel_is_ignored(database) -> None:
    await seed_guild(database)
    await seed_active_spawn(database)
    service = CaptureService(database, GuildLockRegistry())
    result = await service.try_capture(
        CaptureAttempt(1, 11, 200, "thor", utc_now())
    )
    assert not result.captured
    assert result.reason == "wrong_channel"


@pytest.mark.asyncio
async def test_bot_message_is_ignored(database) -> None:
    await seed_guild(database)
    await seed_active_spawn(database)
    service = CaptureService(database, GuildLockRegistry())
    result = await service.try_capture(
        CaptureAttempt(1, 10, 200, "thor", utc_now(), author_is_bot=True)
    )
    assert not result.captured
    assert result.reason == "bot_or_webhook"


@pytest.mark.asyncio
async def test_message_without_active_spawn_is_ignored(database) -> None:
    await seed_guild(database)
    service = CaptureService(database, GuildLockRegistry())
    result = await service.try_capture(CaptureAttempt(1, 10, 200, "thor", utc_now()))
    assert not result.captured
    assert result.reason == "no_active_spawn"


@pytest.mark.asyncio
async def test_concurrent_captures_produce_one_winner(database) -> None:
    await seed_guild(database)
    await seed_active_spawn(database)
    service = CaptureService(database, GuildLockRegistry())
    now = utc_now()
    results = await asyncio.gather(
        service.try_capture(CaptureAttempt(1, 10, 200, "thor", now)),
        service.try_capture(CaptureAttempt(1, 10, 201, "THOR", now + timedelta(milliseconds=1))),
    )
    assert sum(result.captured for result in results) == 1
    count = await database.fetchone("SELECT COUNT(*) AS count FROM captures WHERE guild_id = 1")
    assert int(count["count"]) == 1


@pytest.mark.asyncio
async def test_score_incremented_once(database) -> None:
    await seed_guild(database)
    await seed_active_spawn(database)
    service = CaptureService(database, GuildLockRegistry())
    attempt = CaptureAttempt(1, 10, 200, "thor", utc_now())
    first, second = await asyncio.gather(
        service.try_capture(attempt), service.try_capture(attempt)
    )
    winner = first if first.captured else second
    assert winner.total_captures == 1
    row = await database.fetchone(
        "SELECT COUNT(*) AS total FROM captures WHERE guild_id = 1 AND user_id = 200"
    )
    assert int(row["total"]) == 1


@pytest.mark.asyncio
async def test_collection_quantity_is_updated(database) -> None:
    await seed_guild(database)
    await seed_active_spawn(database, message_id=1000)
    service = CaptureService(database, GuildLockRegistry())
    first = await service.try_capture(CaptureAttempt(1, 10, 200, "thor", utc_now()))
    assert first.collectible_quantity == 1

    await seed_active_spawn(database, message_id=1001)
    second = await service.try_capture(CaptureAttempt(1, 10, 200, "thor", utc_now()))
    assert second.captured
    assert second.collectible_quantity == 2
    row = await database.fetchone(
        """
        SELECT quantity FROM user_collections
        WHERE guild_id = 1 AND user_id = 200 AND collectible_id = 'thor_001'
        """
    )
    assert int(row["quantity"]) == 2


@pytest.mark.asyncio
async def test_reply_and_edited_messages_are_ignored(database) -> None:
    await seed_guild(database)
    await seed_active_spawn(database)
    service = CaptureService(database, GuildLockRegistry())
    reply = await service.try_capture(
        CaptureAttempt(1, 10, 200, "thor", utc_now(), is_reply=True)
    )
    edited = await service.try_capture(
        CaptureAttempt(1, 10, 200, "thor", utc_now(), is_edited=True)
    )
    assert reply.reason == "reply_or_edit"
    assert edited.reason == "reply_or_edit"


@pytest.mark.asyncio
async def test_message_created_before_spawn_is_ignored(database) -> None:
    await seed_guild(database)
    _, spawned_at = await seed_active_spawn(database)
    service = CaptureService(database, GuildLockRegistry())

    result = await service.try_capture(
        CaptureAttempt(1, 10, 200, "thor", spawned_at - timedelta(milliseconds=1))
    )

    assert not result.captured
    assert result.reason == "message_before_spawn"
