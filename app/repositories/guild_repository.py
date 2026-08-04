"""Guild configuration persistence."""

from __future__ import annotations

from app.database import Database
from app.models import GuildConfig, from_utc_iso, to_utc_iso, utc_now


class GuildRepository:
    """Read and update per-guild game configuration."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _from_row(row: object) -> GuildConfig:
        return GuildConfig(
            guild_id=int(row["guild_id"]),  # type: ignore[index]
            channel_id=int(row["channel_id"]),  # type: ignore[index]
            game_admin_user_id=int(row["game_admin_user_id"]),  # type: ignore[index]
            is_active=bool(row["is_active"]),  # type: ignore[index]
            min_spawn_minutes=int(row["min_spawn_minutes"]),  # type: ignore[index]
            max_spawn_minutes=int(row["max_spawn_minutes"]),  # type: ignore[index]
            last_collectible_id=row["last_collectible_id"],  # type: ignore[index]
            created_at=from_utc_iso(str(row["created_at"])),  # type: ignore[index]
            updated_at=from_utc_iso(str(row["updated_at"])),  # type: ignore[index]
        )

    async def get(self, guild_id: int) -> GuildConfig | None:
        """Return one guild configuration, including inactive games."""

        row = await self.database.fetchone(
            "SELECT * FROM guild_configs WHERE guild_id = ?", (guild_id,)
        )
        return self._from_row(row) if row is not None else None

    async def list_active(self) -> list[GuildConfig]:
        """Return every game that should be restored at startup."""

        rows = await self.database.fetchall(
            "SELECT * FROM guild_configs WHERE is_active = 1 ORDER BY guild_id"
        )
        return [self._from_row(row) for row in rows]

    async def create_or_reactivate(
        self,
        guild_id: int,
        channel_id: int,
        admin_user_id: int,
        default_min_minutes: int,
        default_max_minutes: int,
    ) -> GuildConfig:
        """Create a guild or reactivate it without replacing its administrator."""

        now = to_utc_iso(utc_now())
        await self.database.execute(
            """
            INSERT INTO guild_configs(
                guild_id, channel_id, game_admin_user_id, is_active,
                min_spawn_minutes, max_spawn_minutes, last_collectible_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, NULL, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                game_admin_user_id = guild_configs.game_admin_user_id,
                is_active = 1,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                channel_id,
                admin_user_id,
                default_min_minutes,
                default_max_minutes,
                now,
                now,
            ),
            commit=True,
        )
        config = await self.get(guild_id)
        if config is None:
            raise RuntimeError("Guild configuration was not created")
        return config

    async def recover_admin(self, guild_id: int, new_admin_user_id: int) -> None:
        """Transfer game administration to the guild owner during explicit recovery."""

        await self.database.execute(
            """
            UPDATE guild_configs
            SET game_admin_user_id = ?, updated_at = ?
            WHERE guild_id = ?
            """,
            (new_admin_user_id, to_utc_iso(utc_now()), guild_id),
            commit=True,
        )

    async def update_channel_and_activate(self, guild_id: int, channel_id: int) -> None:
        """Move a configured game to another channel and activate it."""

        await self.database.execute(
            """
            UPDATE guild_configs
            SET channel_id = ?, is_active = 1, updated_at = ?
            WHERE guild_id = ?
            """,
            (channel_id, to_utc_iso(utc_now()), guild_id),
            commit=True,
        )

    async def update_interval(
        self, guild_id: int, min_minutes: int, max_minutes: int
    ) -> None:
        """Persist the allowed random delay range for one guild."""

        await self.database.execute(
            """
            UPDATE guild_configs
            SET min_spawn_minutes = ?, max_spawn_minutes = ?, updated_at = ?
            WHERE guild_id = ?
            """,
            (min_minutes, max_minutes, to_utc_iso(utc_now()), guild_id),
            commit=True,
        )

    async def update_last_collectible(self, guild_id: int, collectible_id: str) -> None:
        """Remember the latest item to reduce immediate repetitions."""

        await self.database.execute(
            """
            UPDATE guild_configs
            SET last_collectible_id = ?, updated_at = ?
            WHERE guild_id = ?
            """,
            (collectible_id, to_utc_iso(utc_now()), guild_id),
            commit=True,
        )

    async def deactivate(self, guild_id: int) -> None:
        """Disable scheduling while preserving all guild data."""

        await self.database.execute(
            "UPDATE guild_configs SET is_active = 0, updated_at = ? WHERE guild_id = ?",
            (to_utc_iso(utc_now()), guild_id),
            commit=True,
        )

    async def destroy(self, guild_id: int) -> None:
        """Delete one guild root row and cascade only that guild's game data."""

        await self.database.execute(
            "DELETE FROM guild_configs WHERE guild_id = ?", (guild_id,), commit=True
        )
