"""Per-guild spawn scheduling and Discord message publication."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import discord

from app.models import Collectible, SpawnStatus, utc_now
from app.repositories.guild_repository import GuildRepository
from app.repositories.spawn_repository import SpawnRepository
from app.services.collectible_service import CollectibleService
from app.services.lock_registry import GuildLockRegistry

LOGGER = logging.getLogger(__name__)

REQUIRED_CHANNEL_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("view_channel", "View Channel"),
    ("send_messages", "Send Messages"),
    ("embed_links", "Embed Links"),
    ("attach_files", "Attach Files"),
    ("read_message_history", "Read Message History"),
)


def missing_channel_permissions(channel: discord.abc.GuildChannel, me: discord.Member) -> list[str]:
    """Return human-readable channel permissions missing for the bot member."""

    permissions = channel.permissions_for(me)
    return [
        label
        for attribute, label in REQUIRED_CHANNEL_PERMISSIONS
        if not getattr(permissions, attribute)
    ]


class SpawnManager:
    """Maintain exactly one cancellable waiting task per active guild."""

    def __init__(
        self,
        bot: discord.Client,
        guild_repository: GuildRepository,
        spawn_repository: SpawnRepository,
        collectibles: CollectibleService,
        locks: GuildLockRegistry,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.bot = bot
        self.guild_repository = guild_repository
        self.spawn_repository = spawn_repository
        self.collectibles = collectibles
        self.locks = locks
        self.tasks: dict[int, asyncio.Task[None]] = {}
        self._spawning_guilds: set[int] = set()
        self._stop_requested: set[int] = set()
        self._sleep = sleep
        self._rng = random.SystemRandom()

    async def start_for_guild(self, guild_id: int) -> None:
        """Cancel any previous wait and create one new scheduling task."""

        await self.stop_for_guild(guild_id)
        task = asyncio.create_task(self._wait_and_spawn(guild_id), name=f"spawn-guild-{guild_id}")
        self.tasks[guild_id] = task
        task.add_done_callback(lambda completed, gid=guild_id: self._task_done(gid, completed))
        LOGGER.info("Spawn task started", extra={"guild_id": guild_id})

    async def stop_for_guild(self, guild_id: int) -> None:
        """Cancel and await the current guild task, if any."""

        task = self.tasks.get(guild_id)
        if task is None or task.done():
            self.tasks.pop(guild_id, None)
            return
        if task is asyncio.current_task():
            return
        if guild_id in self._spawning_guilds:
            # Do not cancel a network/database publication half-way through. The task
            # will exit immediately after the critical spawn attempt finishes.
            self._stop_requested.add(guild_id)
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                if self.tasks.get(guild_id) is task:
                    self.tasks.pop(guild_id, None)
                self._stop_requested.discard(guild_id)
            LOGGER.info("Spawn task stopped after publication", extra={"guild_id": guild_id})
            return

        self.tasks.pop(guild_id, None)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        LOGGER.info("Spawn task cancelled", extra={"guild_id": guild_id})

    async def restart_for_guild(self, guild_id: int) -> None:
        """Restart waiting only when no collectible is currently active."""

        if await self.spawn_repository.get_active(guild_id) is None:
            await self.start_for_guild(guild_id)

    async def schedule_next_spawn(self, guild_id: int) -> None:
        """Schedule the next collectible using the guild's current interval."""

        await self.start_for_guild(guild_id)

    def _task_done(self, guild_id: int, task: asyncio.Task[None]) -> None:
        if self.tasks.get(guild_id) is task:
            self.tasks.pop(guild_id, None)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            LOGGER.error(
                "Spawn task failed",
                exc_info=(type(exception), exception, exception.__traceback__),
                extra={"guild_id": guild_id},
            )

    async def _wait_and_spawn(self, guild_id: int) -> None:
        try:
            while True:
                config = await self.guild_repository.get(guild_id)
                if config is None or not config.is_active:
                    return
                if await self.spawn_repository.get_active(guild_id) is not None:
                    return
                delay_minutes = self._rng.randint(
                    config.min_spawn_minutes, config.max_spawn_minutes
                )
                LOGGER.info(
                    "Next spawn scheduled",
                    extra={"guild_id": guild_id, "delay_minutes": delay_minutes},
                )
                await self._sleep(delay_minutes * 60)
                self._spawning_guilds.add(guild_id)
                try:
                    spawned = await self.spawn_collectible(guild_id)
                finally:
                    self._spawning_guilds.discard(guild_id)
                if guild_id in self._stop_requested:
                    return
                if spawned:
                    return
                # A missing image/channel/permission should not kill scheduling forever.
                await self._sleep(60)
        except asyncio.CancelledError:
            LOGGER.debug("Spawn wait cancelled", extra={"guild_id": guild_id})
            raise
        finally:
            self._spawning_guilds.discard(guild_id)

    async def spawn_collectible(self, guild_id: int) -> bool:
        """Publish one collectible after rechecking config and active-spawn state."""

        async with self.locks.get(guild_id):
            config = await self.guild_repository.get(guild_id)
            if config is None or not config.is_active:
                return False
            if await self.spawn_repository.get_active(guild_id) is not None:
                return True

            channel = self.bot.get_channel(config.channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(config.channel_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    LOGGER.warning(
                        "Configured spawn channel is unavailable",
                        extra={"guild_id": guild_id, "channel_id": config.channel_id},
                    )
                    await self.guild_repository.deactivate(guild_id)
                    return False
            if not isinstance(channel, discord.TextChannel):
                LOGGER.warning(
                    "Configured channel is not a text channel",
                    extra={"guild_id": guild_id, "channel_id": config.channel_id},
                )
                return False
            guild = channel.guild
            me = guild.me
            if me is None:
                return False
            missing = missing_channel_permissions(channel, me)
            if missing:
                LOGGER.warning(
                    "Bot lost required channel permissions",
                    extra={"guild_id": guild_id, "missing_permissions": missing},
                )
                return False

            collectible = self.collectibles.choose(config.last_collectible_id)
            if collectible is None:
                LOGGER.error("No enabled collectible has an available image")
                return False
            image_path = self.collectibles.image_path(collectible)
            if not image_path.is_file():
                LOGGER.error(
                    "Collectible image missing",
                    extra={"collectible_id": collectible.collectible_id},
                )
                return False

            spawned_at = utc_now()
            embed = self._spawn_embed(collectible, spawned_at)
            attachment_name = image_path.name
            embed.set_image(url=f"attachment://{attachment_name}")
            try:
                with image_path.open("rb") as image_handle:
                    message = await channel.send(
                        embed=embed,
                        file=discord.File(image_handle, filename=attachment_name),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except (OSError, discord.Forbidden, discord.HTTPException):
                LOGGER.exception(
                    "Unable to publish collectible spawn",
                    extra={"guild_id": guild_id, "collectible_id": collectible.collectible_id},
                )
                return False

            try:
                await self.spawn_repository.create_active(
                    guild_id,
                    channel.id,
                    message.id,
                    collectible.collectible_id,
                    spawned_at,
                )
                await self.guild_repository.update_last_collectible(
                    guild_id, collectible.collectible_id
                )
            except Exception:
                LOGGER.exception(
                    "Spawn message sent but database persistence failed",
                    extra={"guild_id": guild_id, "message_id": message.id},
                )
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                return False

            LOGGER.info(
                "Collectible spawned",
                extra={
                    "guild_id": guild_id,
                    "channel_id": channel.id,
                    "message_id": message.id,
                    "collectible_id": collectible.collectible_id,
                },
            )
            return True

    @staticmethod
    def _spawn_embed(collectible: Collectible, spawned_at: datetime) -> discord.Embed:
        embed = discord.Embed(
            title=f"{collectible.caption} " + "\n\nSIAMO CON ...?", 
            color=discord.Color.green()
        )
        return embed

    async def invalidate_active_spawn(
        self, guild_id: int, *, cancelled: bool = False
    ) -> int:
        """Close the current active spawn without assigning a winner."""

        status = SpawnStatus.CANCELLED if cancelled else SpawnStatus.INVALIDATED
        return await self.spawn_repository.invalidate_active(guild_id, status)

    async def restore_active_guilds(self) -> None:
        """Restore active spawns or one scheduler task for every configured guild."""

        active_configs = await self.guild_repository.list_active()
        for config in active_configs:
            await self.stop_for_guild(config.guild_id)
            active_spawn = await self.spawn_repository.get_active(config.guild_id)
            if active_spawn is not None:
                message_exists = await self._active_message_exists(active_spawn)
                if message_exists:
                    LOGGER.info(
                        "Restored active collectible",
                        extra={"guild_id": config.guild_id, "spawn_id": active_spawn.spawn_id},
                    )
                    continue
                await self.spawn_repository.invalidate_active(config.guild_id)
            await self.start_for_guild(config.guild_id)
        LOGGER.info("Active guilds restored", extra={"guild_count": len(active_configs)})

    async def _active_message_exists(self, spawn: object) -> bool:
        channel = self.bot.get_channel(spawn.channel_id)  # type: ignore[attr-defined]
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(
                    spawn.channel_id  # type: ignore[attr-defined]
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return False
        if not isinstance(channel, discord.TextChannel):
            return False
        try:
            await channel.fetch_message(spawn.message_id)  # type: ignore[attr-defined]
            return True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False

    async def shutdown(self) -> None:
        """Cancel every scheduling task."""

        guild_ids = list(self.tasks)
        for guild_id in guild_ids:
            await self.stop_for_guild(guild_id)
