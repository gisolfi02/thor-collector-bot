"""Game administration and leaderboard slash commands."""

from __future__ import annotations
from pathlib import Path

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.models import GuildConfig, LeaderboardEntry
from app.services.spawn_manager import (
    ForceSpawnResult,
    missing_channel_permissions,
)
from app.views.destroy_confirmation import DestroyConfirmationView

if TYPE_CHECKING:
    from app.bot import ThorCollectorBot

LOGGER = logging.getLogger(__name__)


def can_manage_game(game_admin_user_id: int, user_id: int) -> bool:
    """Return whether a user is the persisted game administrator."""

    return game_admin_user_id == user_id


def validate_spawn_interval(min_minutes: int, max_minutes: int) -> str | None:
    """Return an Italian validation error or None for a valid interval."""

    if min_minutes < 1 or max_minutes < 1:
        return "I valori devono essere interi positivi di almeno 1 minuto."
    if min_minutes > max_minutes:
        return "Il minimo non può essere maggiore del massimo."
    if min_minutes > 10_080 or max_minutes > 10_080:
        return "L'intervallo massimo consentito è 10.080 minuti (7 giorni)."
    return None


class GameCommands(commands.Cog):
    """Slash commands that configure the game and show rankings."""

    def __init__(self, bot: "ThorCollectorBot") -> None:
        self.bot = bot

    @staticmethod
    async def _member_still_present(guild: discord.Guild, user_id: int) -> bool:
        """Check membership via cache and REST, failing closed on API errors."""

        if guild.get_member(user_id) is not None:
            return True
        try:
            await guild.fetch_member(user_id)
            return True
        except discord.NotFound:
            return False
        except (discord.Forbidden, discord.HTTPException):
            # Recovery must never be granted merely because verification failed.
            return True

    async def _deny_or_config(
        self, interaction: discord.Interaction
    ) -> GuildConfig | None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Questo comando può essere usato soltanto in un server Discord.", ephemeral=True
            )
            return None
        config = await self.bot.guild_repository.get(interaction.guild_id)
        if config is None:
            await interaction.response.send_message(
                "Il gioco non è ancora inizializzato. Usa prima `/start`.", ephemeral=True
            )
            return None
        if not can_manage_game(config.game_admin_user_id, interaction.user.id):
            await interaction.response.send_message(
                "Solo l'amministratore del gioco può usare questo comando.", ephemeral=True
            )
            return None
        return config

    @app_commands.command(name="start", description="Avvia o sposta il gioco in questo canale")
    @app_commands.guild_only()
    async def start(self, interaction: discord.Interaction) -> None:
        """Initialize, reactivate, or move the current guild game."""

        guild = interaction.guild
        channel = interaction.channel
        if guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Esegui `/start` in un normale canale testuale del server.", ephemeral=True
            )
            return
        me = guild.me
        if me is None:
            await interaction.response.send_message(
                "Non riesco a verificare i miei permessi nel server.", ephemeral=True
            )
            return
        missing = missing_channel_permissions(channel, me)
        if missing:
            await interaction.response.send_message(
                "Mi mancano questi permessi nel canale: " + ", ".join(missing) + ".",
                ephemeral=True,
            )
            return

        config = await self.bot.guild_repository.get(guild.id)
        if config is not None and interaction.user.id != config.game_admin_user_id:
            admin_still_present = await self._member_still_present(
                guild, config.game_admin_user_id
            )
            owner_recovery = (
                self.bot.settings.allow_guild_owner_recovery
                and interaction.user.id == guild.owner_id
                and not admin_still_present
            )
            if not owner_recovery:
                await interaction.response.send_message(
                    "Il gioco è già configurato e soltanto il suo "
                    "amministratore può spostarlo.",
                    ephemeral=True,
                )
                return

        # Publication can be in flight, so acknowledge before waiting for a clean stop.
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.spawn_manager.stop_for_guild(guild.id)

        denied_after_recheck = False
        should_restore_scheduler = False
        recovered = False
        async with self.bot.locks.get(guild.id):
            # Re-read after stopping: another command may have changed the config.
            config = await self.bot.guild_repository.get(guild.id)
            first_start = config is None
            if config is not None and interaction.user.id != config.game_admin_user_id:
                admin_still_present = await self._member_still_present(
                    guild, config.game_admin_user_id
                )
                owner_recovery = (
                    self.bot.settings.allow_guild_owner_recovery
                    and interaction.user.id == guild.owner_id
                    and not admin_still_present
                )
                if not owner_recovery:
                    active_spawn = await self.bot.spawn_repository.get_active(guild.id)
                    should_restore_scheduler = config.is_active and active_spawn is None
                    denied_after_recheck = True
                else:
                    await self.bot.guild_repository.recover_admin(
                        guild.id, interaction.user.id
                    )
                    recovered = True

            if not denied_after_recheck:
                await self.bot.spawn_manager.invalidate_active_spawn(guild.id)
                if first_start:
                    config = await self.bot.guild_repository.create_or_reactivate(
                        guild.id,
                        channel.id,
                        interaction.user.id,
                        self.bot.settings.default_min_spawn_minutes,
                        self.bot.settings.default_max_spawn_minutes,
                    )
                else:
                    await self.bot.guild_repository.update_channel_and_activate(
                        guild.id, channel.id
                    )
                    config = await self.bot.guild_repository.get(guild.id)

        if denied_after_recheck:
            if should_restore_scheduler:
                await self.bot.spawn_manager.start_for_guild(guild.id)
            await interaction.edit_original_response(
                content=(
                    "Il gioco è già configurato e soltanto il suo "
                    "amministratore può spostarlo."
                )
            )
            return

        await self.bot.spawn_manager.start_for_guild(guild.id)
        assert config is not None
        recovery_note = "\nRecupero proprietario applicato." if recovered else ""
        await interaction.edit_original_response(
            content=(
                f"⚡ **Thor Collector attivato**\n"
                f"Canale: {channel.mention}\n"
                f"Amministratore del gioco: <@{config.game_admin_user_id}>\n"
                f"Intervallo: **{config.min_spawn_minutes}–"
                f"{config.max_spawn_minutes} minuti**\n"
                f"Stato: **attivo**\n"
                "Il prossimo spawn avverrà indicativamente entro questo "
                f"intervallo.{recovery_note}"
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False
            ),
        )

    async def _send_leaderboard(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "La classifica è disponibile soltanto nei server.", ephemeral=True
            )
            return
        entries = await self.bot.collection_repository.get_leaderboard(interaction.guild.id)
        if not entries:
            await interaction.response.send_message(
                "Non ci sono ancora catture in questo server.", ephemeral=True
            )
            return

        top = entries[:10]
        lines = [self._format_leaderboard_entry(interaction.guild, entry) for entry in top]
        requester_entry = next(
            (entry for entry in entries if entry.user_id == interaction.user.id), None
        )
        if requester_entry is not None and requester_entry.rank > 10:
            lines.extend(
                [
                    "",
                    "**La tua posizione**",
                    self._format_leaderboard_entry(interaction.guild, requester_entry),
                ]
            )
        embed = discord.Embed(
            title="🏅 All Thor Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )

    @staticmethod
    def _format_leaderboard_entry(
        guild: discord.Guild, entry: LeaderboardEntry
    ) -> str:
        prefix = entry.rank
        member = guild.get_member(entry.user_id)
        display_name = (
            discord.utils.escape_markdown(member.display_name)
            if member is not None
            else f"<@{entry.user_id}>"
        )
        return (
            f"{prefix}. **{entry.total_captures}** thor: {display_name}"
        )

    @app_commands.command(name="leaderboard", description="Mostra la classifica delle catture")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        """Show the correctly spelled leaderboard alias."""

        await self._send_leaderboard(interaction)

    @app_commands.command(
        name="changetime", description="Modifica l'intervallo casuale degli spawn"
    )
    @app_commands.describe(
        min_minutes="Intervallo minimo in minuti",
        max_minutes="Intervallo massimo in minuti",
    )
    @app_commands.guild_only()
    async def changetime(
        self, interaction: discord.Interaction, min_minutes: int, max_minutes: int
    ) -> None:
        """Validate and persist a new per-guild spawn interval."""

        config = await self._deny_or_config(interaction)
        if config is None or interaction.guild_id is None:
            return
        error = validate_spawn_interval(min_minutes, max_minutes)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.guild_repository.update_interval(
            interaction.guild_id, min_minutes, max_minutes
        )
        await self.bot.spawn_manager.restart_for_guild(interaction.guild_id)
        LOGGER.info(
            "Spawn interval changed",
            extra={
                "guild_id": interaction.guild_id,
                "min_minutes": min_minutes,
                "max_minutes": max_minutes,
            },
        )
        await interaction.edit_original_response(
            content=(
                f"Intervallo aggiornato a **{min_minutes}–{max_minutes} minuti**. "
                "Un eventuale spawn attivo rimane catturabile."
            )
        )

    @app_commands.command(name="destroy", description="Elimina definitivamente il gioco del server")
    @app_commands.guild_only()
    async def destroy(self, interaction: discord.Interaction) -> None:
        """Ask the game administrator to confirm irreversible deletion."""

        config = await self._deny_or_config(interaction)
        if config is None or interaction.guild_id is None:
            return
        guild_id = interaction.guild_id

        async def confirmed(button_interaction: discord.Interaction) -> None:
            """Delete this guild after the requester presses confirmation."""

            await self.bot.destroy_guild_data(guild_id)
            await button_interaction.edit_original_response(
                content=(
                    "Gioco eliminato definitivamente per questo server. "
                    "Classifica, collezioni, configurazione e storico sono stati rimossi."
                ),
                embed=None,
                view=None,
            )

        view = DestroyConfirmationView(interaction.user.id, confirmed)
        embed = discord.Embed(
            title="⚠️ Eliminazione irreversibile",
            description=(
                "Questa operazione cancellerà configurazione, amministratore del gioco, "
                "classifica, collezioni, catture e storico degli spawn "
                "**solo per questo server**.\n\n"
                "Conferma entro 30 secondi."
            ),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(
        name="thor",
        description="Mostra una foto casuale di Thor solo per visualizzazione.",
    )
    async def thor(self, interaction: discord.Interaction) -> None:
        """Show a random collectible as a non-capturable preview."""

        if interaction.guild is None:
            await interaction.response.send_message(
                "Questo comando può essere usato solo in un server.",
                ephemeral=True,
            )
            return

        collectible = self.bot.collectibles.choose()
        if collectible is None:
            await interaction.response.send_message(
                "Non ci sono foto disponibili da mostrare al momento.",
                ephemeral=True,
            )
            return

        image_path = self.bot.collectibles.image_path(collectible)
        if not image_path.is_file():
            await interaction.response.send_message(
                "L'immagine associata a questa foto non è disponibile.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"{collectible.name}",
            color=discord.Color(0x00AEEF),
        )

        embed.add_field(name="Rarità", value=collectible.rarity, inline=True)
        file = discord.File(
            image_path,
            filename=image_path.name,
        )
        embed.set_image(url=f"attachment://{image_path.name}")

        await interaction.response.send_message(
            embed=embed,
            file=file,
        )

    @app_commands.command(
      name="forcespawn",
      description="Fa apparire immediatamente una foto catturabile",
    )
    @app_commands.guild_only()
    async def forcespawn(self, interaction: discord.Interaction) -> None:
        """Cancel the pending wait and publish a capturable spawn immediately."""

        config = await self._deny_or_config(interaction)

        if config is None or interaction.guild_id is None:
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        result = await self.bot.spawn_manager.force_spawn(
            interaction.guild_id
        )

        if result is ForceSpawnResult.SPAWNED:
            message = (
                f"⚡ Spawn forzato pubblicato in <#{config.channel_id}>.\n"
                "La foto è catturabile normalmente scrivendo `thor`."
            )

        elif result is ForceSpawnResult.ALREADY_ACTIVE:
            message = (
                "Esiste già una foto attiva e catturabile nel canale di gioco. "
                "Deve essere catturata prima di forzarne un'altra."
            )

        elif result is ForceSpawnResult.INACTIVE:
            message = (
                "Il gioco non è attivo. Usa `/start` prima di forzare uno spawn."
            )

        else:
            message = (
                "Non sono riuscito a pubblicare la foto. "
                "Controlla immagini, canale e permessi del bot. "
                "Il normale timer è stato ripristinato."
            )

        LOGGER.info(
            "Force spawn command executed",
            extra={
                "guild_id": interaction.guild_id,
                "user_id": interaction.user.id,
                "result": result.value,
            },
        )

        await interaction.edit_original_response(content=message)
