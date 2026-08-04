"""Spawn history persistence."""

from __future__ import annotations

from datetime import datetime

from app.database import Database
from app.models import Spawn, SpawnStatus, from_utc_iso, to_utc_iso


class SpawnRepository:
    """Create, retrieve, and invalidate collectible spawns."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _from_row(row: object) -> Spawn:
        captured_at_raw = row["captured_at"]  # type: ignore[index]
        captured_by_raw = row["captured_by_user_id"]  # type: ignore[index]
        return Spawn(
            spawn_id=int(row["spawn_id"]),  # type: ignore[index]
            guild_id=int(row["guild_id"]),  # type: ignore[index]
            channel_id=int(row["channel_id"]),  # type: ignore[index]
            message_id=int(row["message_id"]),  # type: ignore[index]
            collectible_id=str(row["collectible_id"]),  # type: ignore[index]
            status=SpawnStatus(str(row["status"])),  # type: ignore[index]
            spawned_at=from_utc_iso(str(row["spawned_at"])),  # type: ignore[index]
            captured_at=from_utc_iso(str(captured_at_raw)) if captured_at_raw else None,
            captured_by_user_id=int(captured_by_raw) if captured_by_raw is not None else None,
        )

    async def get_active(self, guild_id: int) -> Spawn | None:
        """Return the sole active spawn for a guild, when present."""

        row = await self.database.fetchone(
            "SELECT * FROM spawns WHERE guild_id = ? AND status = 'ACTIVE' LIMIT 1",
            (guild_id,),
        )
        return self._from_row(row) if row is not None else None

    async def create_active(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        collectible_id: str,
        spawned_at: datetime,
    ) -> int:
        """Persist a newly published active spawn and return its ID."""

        cursor = await self.database.execute(
            """
            INSERT INTO spawns(
                guild_id, channel_id, message_id, collectible_id, status, spawned_at
            ) VALUES (?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (guild_id, channel_id, message_id, collectible_id, to_utc_iso(spawned_at)),
            commit=True,
        )
        return int(cursor.lastrowid)

    async def invalidate_active(
        self, guild_id: int, status: SpawnStatus = SpawnStatus.INVALIDATED
    ) -> int:
        """Close a guild's active spawn without recording a capture."""

        if status not in {SpawnStatus.INVALIDATED, SpawnStatus.CANCELLED}:
            raise ValueError("Only INVALIDATED or CANCELLED may close an active spawn")
        cursor = await self.database.execute(
            "UPDATE spawns SET status = ? WHERE guild_id = ? AND status = 'ACTIVE'",
            (status.value, guild_id),
            commit=True,
        )
        return cursor.rowcount

    async def count_active(self, guild_id: int) -> int:
        """Count active spawns for integrity checks and tests."""

        row = await self.database.fetchone(
            "SELECT COUNT(*) AS count FROM spawns WHERE guild_id = ? AND status = 'ACTIVE'",
            (guild_id,),
        )
        return int(row["count"]) if row is not None else 0
