"""Set the Discord bot profile banner once."""

import os
from pathlib import Path

import discord
from dotenv import load_dotenv


BANNER_PATH = Path("assets/banner.png")


class BannerClient(discord.Client):
    """Temporary client used only to update the bot banner."""

    async def on_ready(self) -> None:
        if self.user is None:
            print("Errore: utente bot non disponibile.")
            await self.close()
            return

        try:
            if not BANNER_PATH.is_file():
                raise FileNotFoundError(
                    f"Banner non trovato: {BANNER_PATH.resolve()}"
                )

            banner_bytes = BANNER_PATH.read_bytes()

            await self.user.edit(banner=banner_bytes)

            print(
                f"Banner aggiornato correttamente per {self.user}."
            )

        except (discord.HTTPException, ValueError, OSError) as exc:
            print(f"Impossibile aggiornare il banner: {exc}")

        finally:
            await self.close()


def main() -> None:
    """Load configuration and update the bot banner."""

    load_dotenv()

    token = os.getenv("DISCORD_TOKEN")

    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN non configurato nel file .env."
        )

    client = BannerClient(intents=discord.Intents.none())
    client.run(token, log_handler=None)


if __name__ == "__main__":
    main()