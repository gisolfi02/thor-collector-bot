"""Domain models shared across repositories and services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def to_utc_iso(value: datetime) -> str:
    """Serialize a datetime to a normalized UTC ISO-8601 string."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def from_utc_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class SpawnStatus(StrEnum):
    """Allowed lifecycle states for a collectible spawn."""

    ACTIVE = "ACTIVE"
    CAPTURED = "CAPTURED"
    CANCELLED = "CANCELLED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True, slots=True)
class GuildConfig:
    """Persisted configuration for one Discord guild."""

    guild_id: int
    channel_id: int
    game_admin_user_id: int
    is_active: bool
    min_spawn_minutes: int
    max_spawn_minutes: int
    last_collectible_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Collectible:
    """One catalog item that may be spawned and collected."""

    collectible_id: str
    name: str
    filename: str
    caption: str
    description: str
    rarity: str
    is_enabled: bool = True


@dataclass(frozen=True, slots=True)
class Spawn:
    """Persisted lifecycle record for one published collectible."""

    spawn_id: int
    guild_id: int
    channel_id: int
    message_id: int
    collectible_id: str
    status: SpawnStatus
    spawned_at: datetime
    captured_at: datetime | None
    captured_by_user_id: int | None


@dataclass(frozen=True, slots=True)
class CaptureAttempt:
    """Discord-independent facts needed to validate a capture message."""

    guild_id: int | None
    channel_id: int
    user_id: int
    content: str
    created_at: datetime
    author_is_bot: bool = False
    is_reply: bool = False
    is_edited: bool = False
    is_webhook: bool = False


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """Outcome returned after a capture attempt is processed."""

    captured: bool
    reason: str
    spawn_id: int | None = None
    collectible_id: str | None = None
    collectible_name: str | None = None
    rarity: str | None = None
    total_captures: int = 0
    collectible_quantity: int = 0
    capture_time_ms: int = 0


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    """Ranked aggregate statistics for one guild participant."""

    user_id: int
    total_captures: int
    unique_collectibles: int
    first_capture_at: datetime
    rank: int


@dataclass(frozen=True, slots=True)
class CollectionEntry:
    """One collectible and its quantity in a member collection."""

    collectible_id: str
    name: str
    rarity: str
    quantity: int
    first_captured_at: datetime
    last_captured_at: datetime
