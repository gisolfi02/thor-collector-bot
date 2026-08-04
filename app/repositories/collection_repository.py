"""Collection and leaderboard queries."""

from __future__ import annotations

from app.database import Database
from app.models import CollectionEntry, LeaderboardEntry, from_utc_iso


class CollectionRepository:
    """Query user collections, totals, and ranked capture statistics."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_collection(self, guild_id: int, user_id: int) -> list[CollectionEntry]:
        """Return every collected item and quantity for one guild member."""

        rows = await self.database.fetchall(
            """
            SELECT uc.collectible_id, c.name, c.rarity, uc.quantity,
                   uc.first_captured_at, uc.last_captured_at
            FROM user_collections AS uc
            JOIN collectibles AS c ON c.collectible_id = uc.collectible_id
            WHERE uc.guild_id = ? AND uc.user_id = ?
            ORDER BY
                CASE c.rarity
                    WHEN 'Leggendario' THEN 1
                    WHEN 'Epico' THEN 2
                    WHEN 'Raro' THEN 3
                    WHEN 'Non comune' THEN 4
                    WHEN 'Comune' THEN 5
                    ELSE 6
                END,
                c.name COLLATE NOCASE
            """,
            (guild_id, user_id),
        )
        return [
            CollectionEntry(
                collectible_id=str(row["collectible_id"]),
                name=str(row["name"]),
                rarity=str(row["rarity"]),
                quantity=int(row["quantity"]),
                first_captured_at=from_utc_iso(str(row["first_captured_at"])),
                last_captured_at=from_utc_iso(str(row["last_captured_at"])),
            )
            for row in rows
        ]

    async def get_summary(self, guild_id: int, user_id: int) -> tuple[int, int]:
        """Return total copies and unique collectible count for a member."""

        row = await self.database.fetchone(
            """
            SELECT COALESCE(SUM(quantity), 0) AS total,
                   COUNT(*) AS unique_count
            FROM user_collections
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )
        if row is None:
            return (0, 0)
        return int(row["total"]), int(row["unique_count"])

    async def get_leaderboard(self, guild_id: int) -> list[LeaderboardEntry]:
        """Return all participants ordered by the documented tie-break rules."""

        rows = await self.database.fetchall(
            """
            WITH stats AS (
                SELECT user_id,
                       COUNT(*) AS total_captures,
                       COUNT(DISTINCT collectible_id) AS unique_collectibles,
                       MIN(captured_at) AS first_capture_at
                FROM captures
                WHERE guild_id = ?
                GROUP BY user_id
            ), ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    ORDER BY total_captures DESC,
                             unique_collectibles DESC,
                             first_capture_at ASC,
                             user_id ASC
                ) AS rank
                FROM stats
            )
            SELECT * FROM ranked ORDER BY rank
            """,
            (guild_id,),
        )
        return [
            LeaderboardEntry(
                user_id=int(row["user_id"]),
                total_captures=int(row["total_captures"]),
                unique_collectibles=int(row["unique_collectibles"]),
                first_capture_at=from_utc_iso(str(row["first_capture_at"])),
                rank=int(row["rank"]),
            )
            for row in rows
        ]
