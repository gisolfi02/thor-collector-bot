"""Button-based pagination for large collections."""

from __future__ import annotations

import discord


def can_control_collection(requester_id: int, actor_id: int) -> bool:
    """Return whether a user may operate collection pagination controls."""

    return requester_id == actor_id


class CollectionPaginationView(discord.ui.View):
    """Show collection pages that only the requester may control."""

    def disable_all_items(self) -> None:
        """Disable every interactive child in a discord.py-compatible way."""

        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True

    def __init__(self, requester_id: int, pages: list[discord.Embed]) -> None:
        super().__init__(timeout=120)
        if not pages:
            raise ValueError("CollectionPaginationView requires at least one page")
        self.requester_id = requester_id
        self.pages = pages
        self.page_index = 0
        self.message: discord.InteractionMessage | None = None
        self._refresh_buttons()

    @property
    def current_embed(self) -> discord.Embed:
        """Return the embed for the currently selected page."""

        return self.pages[self.page_index]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Allow only the member who opened the pagination view."""

        if can_control_collection(self.requester_id, interaction.user.id):
            return True
        await interaction.response.send_message(
            "Solo chi ha richiesto la collezione può usare questi pulsanti.", ephemeral=True
        )
        return False

    def _refresh_buttons(self) -> None:
        self.previous.disabled = self.page_index == 0
        self.next.disabled = self.page_index >= len(self.pages) - 1

    @discord.ui.button(label="Precedente", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["CollectionPaginationView"],
    ) -> None:
        """Move to the previous collection page."""

        self.page_index = max(0, self.page_index - 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.current_embed, view=self)

    @discord.ui.button(label="Successiva", style=discord.ButtonStyle.primary, emoji="➡️")
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["CollectionPaginationView"],
    ) -> None:
        """Move to the next collection page."""

        self.page_index = min(len(self.pages) - 1, self.page_index + 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.current_embed, view=self)

    @discord.ui.button(label="Chiudi", style=discord.ButtonStyle.danger, emoji="✖️")
    async def close_view(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["CollectionPaginationView"],
    ) -> None:
        """Disable pagination controls at the requester's command."""

        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self) -> None:
        """Disable stale controls after the view timeout."""

        self.disable_all_items()
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
