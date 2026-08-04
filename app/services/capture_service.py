"""Atomic capture processing independent from Discord network calls."""

from __future__ import annotations

import logging
from datetime import timezone

from app.database import Database
from app.models import CaptureAttempt, CaptureResult, from_utc_iso, to_utc_iso
from app.services.lock_registry import GuildLockRegistry

LOGGER = logging.getLogger(__name__)


def is_capture_text(content: str) -> bool:
    """Return True only when content is exactly `thor`, ignoring case and edge spaces."""

    return content.strip().casefold() == "thor"


class CaptureService:
    """Validate and atomically persist a capture attempt."""

    def __init__(self, database: Database, locks: GuildLockRegistry) -> None:
        self.database = database
        self.locks = locks

    async def try_capture(self, attempt: CaptureAttempt) -> CaptureResult:
        """Persist a valid capture if the guild still has an active spawn."""

        if attempt.guild_id is None:
            return CaptureResult(False, "not_in_guild")
        if attempt.author_is_bot or attempt.is_webhook:
            return CaptureResult(False, "bot_or_webhook")
        if attempt.is_reply or attempt.is_edited:
            return CaptureResult(False, "reply_or_edit")
        if not is_capture_text(attempt.content):
            return CaptureResult(False, "invalid_text")

        guild_id = attempt.guild_id
        async with self.locks.get(guild_id):
            config = await self.database.fetchone(
                "SELECT channel_id, is_active FROM guild_configs WHERE guild_id = ?",
                (guild_id,),
            )
            if config is None or not bool(config["is_active"]):
                return CaptureResult(False, "guild_inactive")
            if int(config["channel_id"]) != attempt.channel_id:
                return CaptureResult(False, "wrong_channel")

            async with self.database.transaction() as connection:
                cursor = await connection.execute(
                    """
                    SELECT s.spawn_id, s.message_id, s.collectible_id, s.spawned_at,
                           c.name, c.rarity
                    FROM spawns AS s
                    JOIN collectibles AS c ON c.collectible_id = s.collectible_id
                    WHERE s.guild_id = ? AND s.status = 'ACTIVE'
                    LIMIT 1
                    """,
                    (guild_id,),
                )
                row = await cursor.fetchone()
                await cursor.close()
                if row is None:
                    return CaptureResult(False, "no_active_spawn")

                spawned_at = from_utc_iso(str(row["spawned_at"]))
                message_time = attempt.created_at
                if message_time.tzinfo is None:
                    message_time = message_time.replace(tzinfo=timezone.utc)
                message_time = message_time.astimezone(timezone.utc)
                if message_time < spawned_at:
                    return CaptureResult(False, "message_before_spawn")

                captured_at = message_time
                capture_time_ms = max(0, int((captured_at - spawned_at).total_seconds() * 1000))
                update = await connection.execute(
                    """
                    UPDATE spawns
                    SET status = 'CAPTURED', captured_at = ?, captured_by_user_id = ?
                    WHERE spawn_id = ? AND status = 'ACTIVE'
                    """,
                    (to_utc_iso(captured_at), attempt.user_id, int(row["spawn_id"])),
                )
                if update.rowcount != 1:
                    return CaptureResult(False, "already_captured")

                await connection.execute(
                    """
                    INSERT INTO captures(
                        guild_id, user_id, collectible_id, spawn_id,
                        captured_at, capture_time_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        attempt.user_id,
                        str(row["collectible_id"]),
                        int(row["spawn_id"]),
                        to_utc_iso(captured_at),
                        capture_time_ms,
                    ),
                )
                await connection.execute(
                    """
                    INSERT INTO user_collections(
                        guild_id, user_id, collectible_id, quantity,
                        first_captured_at, last_captured_at
                    ) VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(guild_id, user_id, collectible_id) DO UPDATE SET
                        quantity = user_collections.quantity + 1,
                        last_captured_at = excluded.last_captured_at
                    """,
                    (
                        guild_id,
                        attempt.user_id,
                        str(row["collectible_id"]),
                        to_utc_iso(captured_at),
                        to_utc_iso(captured_at),
                    ),
                )
                totals_cursor = await connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM captures WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, attempt.user_id),
                )
                totals = await totals_cursor.fetchone()
                await totals_cursor.close()
                quantity_cursor = await connection.execute(
                    """
                    SELECT quantity FROM user_collections
                    WHERE guild_id = ? AND user_id = ? AND collectible_id = ?
                    """,
                    (guild_id, attempt.user_id, str(row["collectible_id"])),
                )
                quantity_row = await quantity_cursor.fetchone()
                await quantity_cursor.close()

            result = CaptureResult(
                captured=True,
                reason="captured",
                spawn_id=int(row["spawn_id"]),
                spawn_message_id=int(row["message_id"]),
                collectible_id=str(row["collectible_id"]),
                collectible_name=str(row["name"]),
                rarity=str(row["rarity"]),
                total_captures=int(totals["total"]),
                collectible_quantity=int(quantity_row["quantity"]),
                capture_time_ms=capture_time_ms,
            )
            LOGGER.info(
                "Capture persisted",
                extra={
                    "guild_id": guild_id,
                    "user_id": attempt.user_id,
                    "spawn_id": result.spawn_id,
                    "collectible_id": result.collectible_id,
                },
            )
            return result
