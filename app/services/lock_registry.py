"""Per-guild lock registry shared by capture and scheduling services."""

from __future__ import annotations

import asyncio
from collections import defaultdict


class GuildLockRegistry:
    """Provide one asyncio lock per Discord guild."""

    def __init__(self) -> None:
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get(self, guild_id: int) -> asyncio.Lock:
        """Return the stable lock associated with a guild ID."""

        return self._locks[guild_id]

    def discard(self, guild_id: int) -> None:
        """Forget an unused lock after a guild has been destroyed or removed."""

        lock = self._locks.get(guild_id)
        if lock is not None and not lock.locked():
            self._locks.pop(guild_id, None)
