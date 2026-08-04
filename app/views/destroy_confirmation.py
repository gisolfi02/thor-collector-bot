"""Confirmation buttons for the destructive /destroy command."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging

import discord

LOGGER = logging.getLogger(__name__)


class DestroyConfirmationView(discord.ui.View):
    """Restrict a destructive confirmation to the requesting user."""

    def disable_all_items(self) -> None:
        """Disable every interactive child in a discord.py-compatible way."""

        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True

    def __init__(
        self,
        requester_id: int,
        on_confirm: Callable[[discord.Interaction], Awaitable[None]],
    ) -> None:
        super().__init__(timeout=30)
        self.requester_id = requester_id
        self.on_confirm_callback = on_confirm
        self.message: discord.InteractionMessage | None = None
        self.completed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Allow only the administrator who issued `/destroy`."""

        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            "Solo chi ha eseguito `/destroy` può usare questi pulsanti.", ephemeral=True
        )
        return False

    @discord.ui.button(
        label="Conferma eliminazione",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button["DestroyConfirmationView"]
    ) -> None:
        """Run the injected destructive callback after confirmation."""

        self.completed = True
        self.disable_all_items()
        await interaction.response.defer(ephemeral=True)
        await self.on_confirm_callback(interaction)
        self.stop()

    @discord.ui.button(label="Annulla", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button["DestroyConfirmationView"]
    ) -> None:
        """Cancel deletion and leave all persistent data untouched."""

        self.completed = True
        self.disable_all_items()
        await interaction.response.edit_message(
            content="Operazione annullata. Nessun dato è stato eliminato.",
            embed=None,
            view=self,
        )
        self.stop()

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        """Log component failures and replace the confirmation with a safe error."""

        LOGGER.exception(
            "Destroy confirmation failed",
            exc_info=(type(error), error, error.__traceback__),
            extra={"requester_id": self.requester_id},
        )
        message = "Eliminazione non completata. Controlla i log e riprova."
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(
                    content=message, embed=None, view=None
                )
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            LOGGER.exception("Unable to report destroy confirmation failure")
        self.stop()

    async def on_timeout(self) -> None:
        """Expire the confirmation safely after 30 seconds."""

        if self.completed:
            return
        self.disable_all_items()
        if self.message is not None:
            try:
                await self.message.edit(
                    content="Conferma scaduta. Nessun dato è stato eliminato.",
                    embed=None,
                    view=self,
                )
            except discord.HTTPException:
                pass

