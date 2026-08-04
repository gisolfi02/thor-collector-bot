"""Collection browsing slash command."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.models import CollectionEntry
from app.views.collection_pagination import CollectionPaginationView

if TYPE_CHECKING:
    from app.bot import ThorCollectorBot


class CollectionCommands(commands.Cog):
    """Expose paginated user collections."""

    PAGE_SIZE = 8

    def __init__(self, bot: "ThorCollectorBot") -> None:
        self.bot = bot

    @app_commands.command(name="collection", description="Mostra una collezione del server")
    @app_commands.describe(user="Utente di cui visualizzare la collezione")
    @app_commands.guild_only()
    async def collection(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        """Show the selected member's collection with requester-only pagination."""

        if interaction.guild is None:
            await interaction.response.send_message(
                "La collezione è disponibile soltanto nei server.", ephemeral=True
            )
            return
        target = user or interaction.user
        entries = await self.bot.collection_repository.get_collection(
            interaction.guild.id, target.id
        )
        total, unique_count = await self.bot.collection_repository.get_summary(
            interaction.guild.id, target.id
        )
        enabled_ids = self.bot.collectibles.enabled_ids
        catalog_count = len(enabled_ids)
        current_unique_count = sum(
            1 for entry in entries if entry.collectible_id in enabled_ids
        )
        completion = (current_unique_count / catalog_count * 100) if catalog_count else 0.0
        pages = self._build_pages(target, entries, total)
        view = CollectionPaginationView(interaction.user.id, pages) if len(pages) > 1 else None
        await interaction.response.send_message(
            embed=pages[0],
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        if view is not None:
            view.message = await interaction.original_response()

    def _build_pages(
        self,
        target: discord.abc.User,
        entries: list[CollectionEntry],
        total: int,
    ) -> list[discord.Embed]:
        if not entries:
            embed = discord.Embed(
                description=f"📚 Collezione di <@{target.id}>" + "Non hai ancora catturato alcun thor.",
                color=discord.Color.red()
            )
            embed.add_field(name="Catture totali", value="0")
            return [embed]

        page_count = math.ceil(len(entries) / self.PAGE_SIZE)
        pages: list[discord.Embed] = []
        for page_index in range(page_count):
            start = page_index * self.PAGE_SIZE
            page_entries = entries[start : start + self.PAGE_SIZE]
            lines = [
                f"{entry.quantity} **{discord.utils.escape_markdown(entry.name)}** — "
                f"{discord.utils.escape_markdown(entry.rarity)} "
                for entry in page_entries
            ]
            embed = discord.Embed(
                description=f"📚 **{"Collezione di"}** <@{target.id}>\n\n"+ "\n".join(lines),
                color=discord.Color.blue()
            )
            pages.append(embed)
        return pages
