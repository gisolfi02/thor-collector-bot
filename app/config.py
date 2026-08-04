"""Environment-based application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Invalid boolean value: {value!r}")


def _parse_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value < 1:
        raise ConfigError(f"{name} must be at least 1")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings."""

    discord_token: str
    database_path: Path
    log_level: str
    default_min_spawn_minutes: int
    default_max_spawn_minutes: int
    allow_guild_owner_recovery: bool
    test_guild_id: int | None
    catalog_path: Path
    collectibles_dir: Path
    health_file: Path

    @classmethod
    def from_environment(cls) -> "Settings":
        """Load and validate settings from the environment and optional .env file."""

        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ConfigError(
                "DISCORD_TOKEN is not configured. Copy .env.example to .env and add the bot token."
            )

        min_minutes = _parse_positive_int("DEFAULT_MIN_SPAWN_MINUTES", 30)
        max_minutes = _parse_positive_int("DEFAULT_MAX_SPAWN_MINUTES", 90)
        if min_minutes > max_minutes:
            raise ConfigError(
                "DEFAULT_MIN_SPAWN_MINUTES cannot exceed DEFAULT_MAX_SPAWN_MINUTES"
            )
        if max_minutes > 10_080:
            raise ConfigError("Default spawn interval cannot exceed 10,080 minutes")

        test_guild_raw = os.getenv("TEST_GUILD_ID", "").strip()
        test_guild_id: int | None = None
        if test_guild_raw:
            try:
                test_guild_id = int(test_guild_raw)
            except ValueError as exc:
                raise ConfigError("TEST_GUILD_ID must be a Discord snowflake integer") from exc
            if test_guild_id <= 0:
                raise ConfigError("TEST_GUILD_ID must be positive")

        root = Path(__file__).resolve().parents[1]
        database_path = Path(os.getenv("DATABASE_PATH", str(root / "data" / "thor_bot.sqlite3")))
        catalog_path = Path(
            os.getenv("COLLECTIBLES_JSON", str(root / "assets" / "collectibles.json"))
        )
        collectibles_dir = Path(
            os.getenv("COLLECTIBLES_DIR", str(root / "assets" / "collectibles"))
        )
        health_file = Path(os.getenv("HEALTH_FILE", "/tmp/thor-bot-health"))

        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if log_level not in allowed_levels:
            raise ConfigError(f"LOG_LEVEL must be one of: {', '.join(sorted(allowed_levels))}")

        return cls(
            discord_token=token,
            database_path=database_path,
            log_level=log_level,
            default_min_spawn_minutes=min_minutes,
            default_max_spawn_minutes=max_minutes,
            allow_guild_owner_recovery=_parse_bool(
                os.getenv("ALLOW_GUILD_OWNER_RECOVERY"), default=False
            ),
            test_guild_id=test_guild_id,
            catalog_path=catalog_path,
            collectibles_dir=collectibles_dir,
            health_file=health_file,
        )
