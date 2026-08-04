"""Application entry point: `python -m app.main`."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Any

import discord

from app.bot import ThorCollectorBot
from app.config import ConfigError, Settings
from app.database import DatabaseError
from app.services.collectible_service import CatalogError


class JsonLogFormatter(logging.Formatter):
    """Emit readable single-line JSON logs without secrets or chat content."""

    STANDARD_ATTRIBUTES = set(logging.makeLogRecord({}).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        """Serialize one log record to a compact JSON object."""

        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self.STANDARD_ATTRIBUTES and key not in {"message", "asctime"}:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    """Configure root and discord.py logging."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("discord").setLevel(max(logging.INFO, logging.getLevelName(level)))


async def run_bot(settings: Settings) -> None:
    """Run until Discord closes or SIGINT/SIGTERM requests shutdown."""

    bot = ThorCollectorBot(settings)
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        """Schedule graceful shutdown from an operating-system signal."""

        asyncio.create_task(bot.close())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except (NotImplementedError, RuntimeError):
            # add_signal_handler is unavailable on the default Windows event loop.
            pass

    async with bot:
        await bot.start(settings.discord_token, reconnect=True)


def main() -> int:
    """Validate configuration and run the bot with clear startup failures."""

    try:
        settings = Settings.from_environment()
        configure_logging(settings.log_level)
        logging.getLogger(__name__).info("Thor Collector Bot starting")
        asyncio.run(run_bot(settings))
        return 0
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
    except discord.LoginFailure:
        print("Discord authentication failed: DISCORD_TOKEN is invalid.", file=sys.stderr)
    except (DatabaseError, CatalogError) as exc:
        print(f"Startup error: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.getLogger(__name__).exception("Fatal bot error")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
