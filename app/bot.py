"""Discord client composition and event handling."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.collection_commands import CollectionCommands
from app.cogs.game_commands import GameCommands
from app.config import Settings
from app.database import Database
from app.models import CaptureAttempt
from app.repositories.collection_repository import CollectionRepository
from app.repositories.guild_repository import GuildRepository
from app.repositories.spawn_repository import SpawnRepository
from app.services.capture_service import CaptureService
from app.services.collectible_service import CollectibleService
from app.services.lock_registry import GuildLockRegistry
from app.services.spawn_manager import SpawnManager

LOGGER = logging.getLogger(__name__)


def format_duration_ms(duration_ms: int) -> str:
    """Formatta una durata in millisecondi usando unità di tempo leggibili."""

    duration_ms = max(0, duration_ms)

    if duration_ms < 1000:
        unit = "millisecondo" if duration_ms == 1 else "millisecondi"
        return f"{duration_ms} {unit}"

    if duration_ms < 60_000:
        seconds = duration_ms / 1000
        formatted_seconds = f"{seconds:.2f}".rstrip("0").rstrip(".")
        formatted_seconds = formatted_seconds.replace(".", ",")

        unit = "secondo" if duration_ms == 1000 else "secondi"
        return f"{formatted_seconds} {unit}"

    total_seconds = duration_ms // 1000

    days, remaining_seconds = divmod(total_seconds, 86_400)
    hours, remaining_seconds = divmod(remaining_seconds, 3_600)
    minutes, seconds = divmod(remaining_seconds, 60)

    parts: list[str] = []

    if days:
        unit = "giorno" if days == 1 else "giorni"
        parts.append(f"{days} {unit}")

    if hours:
        unit = "ora" if hours == 1 else "ore"
        parts.append(f"{hours} {unit}")

    if minutes:
        unit = "minuto" if minutes == 1 else "minuti"
        parts.append(f"{minutes} {unit}")

    if seconds:
        unit = "secondo" if seconds == 1 else "secondi"
        parts.append(f"{seconds} {unit}")

    if len(parts) == 1:
        return parts[0]

    return ", ".join(parts[:-1]) + f" e {parts[-1]}"

class ThorCollectorBot(commands.Bot):
    """Top-level Discord bot with injected repositories and services."""

    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        self.settings = settings
        self.database = Database(settings.database_path)
        self.guild_repository = GuildRepository(self.database)
        self.spawn_repository = SpawnRepository(self.database)
        self.collection_repository = CollectionRepository(self.database)
        self.locks = GuildLockRegistry()
        self.collectibles = CollectibleService(
            self.database, settings.catalog_path, settings.collectibles_dir
        )
        self.capture_service = CaptureService(self.database, self.locks)
        self.spawn_manager = SpawnManager(
            self,
            self.guild_repository,
            self.spawn_repository,
            self.collectibles,
            self.locks,
        )
        self._restored = False
        self._restore_lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._close_lock = asyncio.Lock()
        self._closed_once = False
        self.tree.error(self._on_app_command_error)

    async def setup_hook(self) -> None:
        """Initialize persistence, catalog, cogs, commands, and health heartbeat."""

        await self.database.connect()
        await self.collectibles.synchronize()
        await self.add_cog(GameCommands(self))
        await self.add_cog(CollectionCommands(self))

        if self.settings.test_guild_id is not None:
            guild_object = discord.Object(id=self.settings.test_guild_id)
            self.tree.copy_global_to(guild=guild_object)
            synced = await self.tree.sync(guild=guild_object)
            LOGGER.info(
                "Test-guild commands synchronized",
                extra={"guild_id": self.settings.test_guild_id, "command_count": len(synced)},
            )
        else:
            synced = await self.tree.sync()
            LOGGER.info("Global commands synchronized", extra={"command_count": len(synced)})

        self._heartbeat_task = asyncio.create_task(
            self._health_heartbeat(), name="health-heartbeat"
        )

    async def on_ready(self) -> None:
        """Restore persisted state once the Discord cache is available."""

        LOGGER.info(
            "Connected to Discord",
            extra={
                "bot_user_id": self.user.id if self.user else None,
                "guild_count": len(self.guilds),
            },
        )
        async with self._restore_lock:
            if not self._restored:
                await self.spawn_manager.restore_active_guilds()
                self._restored = True
        self._touch_health_file()

    async def on_resumed(self) -> None:
        """Refresh health state after Discord resumes a gateway session."""

        LOGGER.info("Discord gateway session resumed")
        self._touch_health_file()

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Stop this guild's scheduler while preserving data for a future reinvite."""

        await self.spawn_manager.stop_for_guild(guild.id)
        await self.spawn_manager.invalidate_active_spawn(guild.id)
        await self.guild_repository.deactivate(guild.id)
        self.locks.discard(guild.id)
        LOGGER.info("Bot removed from guild; game deactivated", extra={"guild_id": guild.id})

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        """Invalidate a deleted active spawn and schedule its replacement."""

        if payload.guild_id is None:
            return
        active = await self.spawn_repository.get_active(payload.guild_id)
        if active is None or active.message_id != payload.message_id:
            return
        async with self.locks.get(payload.guild_id):
            active = await self.spawn_repository.get_active(payload.guild_id)
            if active is None or active.message_id != payload.message_id:
                return
            await self.spawn_manager.invalidate_active_spawn(payload.guild_id)
        LOGGER.info(
            "Active spawn message deleted",
            extra={"guild_id": payload.guild_id, "message_id": payload.message_id},
        )
        await self.spawn_manager.schedule_next_spawn(payload.guild_id)

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Deactivate a game whose configured spawn channel was deleted."""

        config = await self.guild_repository.get(channel.guild.id)
        if config is None or config.channel_id != channel.id:
            return
        await self.spawn_manager.stop_for_guild(channel.guild.id)
        async with self.locks.get(channel.guild.id):
            await self.spawn_manager.invalidate_active_spawn(channel.guild.id)
            await self.guild_repository.deactivate(channel.guild.id)
        LOGGER.warning(
            "Configured spawn channel deleted; game deactivated",
            extra={"guild_id": channel.guild.id, "channel_id": channel.id},
        )

    async def on_message(self, message: discord.Message) -> None:
        """Process only exact, newly-created `thor` capture messages."""

        attempt = CaptureAttempt(
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id,
            user_id=message.author.id,
            content=message.content,
            created_at=message.created_at,
            author_is_bot=message.author.bot,
            is_reply=message.reference is not None,
            is_edited=message.edited_at is not None,
            is_webhook=message.webhook_id is not None,
        )
        try:
            result = await self.capture_service.try_capture(attempt)
        except Exception:
            LOGGER.exception(
                "Capture processing failed",
                extra={"guild_id": attempt.guild_id, "channel_id": attempt.channel_id},
            )
            return
        if not result.captured or attempt.guild_id is None:
            return

        formatted_capture_time = format_duration_ms(result.capture_time_ms)
        try:
            await message.channel.send(
                content=f"{message.author.mention} ha catturato {result.collectible_name}!\nRarità: **{result.rarity}**\nOra hai {result.collectible_quantity} thor di questo tipo.\nCatturato in {formatted_capture_time}.",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.exception(
                "Capture saved but winner announcement failed",
                extra={"guild_id": attempt.guild_id, "spawn_id": result.spawn_id},
            )
        finally:
            await self.spawn_manager.schedule_next_spawn(attempt.guild_id)

    async def destroy_guild_data(self, guild_id: int) -> None:
        """Irreversibly delete one guild's game data and stop its task."""

        await self.spawn_manager.stop_for_guild(guild_id)
        async with self.locks.get(guild_id):
            await self.spawn_manager.invalidate_active_spawn(guild_id, cancelled=True)
            await self.guild_repository.destroy(guild_id)
        self.locks.discard(guild_id)
        LOGGER.warning("Guild game destroyed", extra={"guild_id": guild_id})

    async def _on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        LOGGER.exception(
            "Slash command failed",
            exc_info=(type(error), error, error.__traceback__),
            extra={
                "guild_id": interaction.guild_id,
                "command": interaction.command.qualified_name if interaction.command else None,
            },
        )
        message = "Si è verificato un errore. Riprova tra poco; i dettagli sono nei log del bot."
        with suppress(discord.HTTPException):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

    async def _health_heartbeat(self) -> None:
        try:
            while True:
                self._touch_health_file()
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except OSError:
            LOGGER.exception("Unable to update health file")

    def _touch_health_file(self) -> None:
        try:
            self.settings.health_file.parent.mkdir(parents=True, exist_ok=True)
            self.settings.health_file.touch()
        except OSError:
            LOGGER.exception("Unable to touch health file")

    async def close(self) -> None:
        """Cancel tasks and close Discord and SQLite cleanly."""

        async with self._close_lock:
            if self._closed_once:
                return
            self._closed_once = True
            LOGGER.info("Bot shutdown started")
            await self.spawn_manager.shutdown()
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._heartbeat_task
                self._heartbeat_task = None
            await self.database.close()
            await super().close()
            LOGGER.info("Bot shutdown complete")
