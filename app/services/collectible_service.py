"""Collectible catalog validation, synchronization, and random selection."""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from app.database import Database
from app.models import Collectible

LOGGER = logging.getLogger(__name__)


class CatalogError(RuntimeError):
    """Raised when the collectible JSON catalog is invalid."""


class CollectibleService:
    """Load the JSON catalog and mirror enabled entries into SQLite."""

    REQUIRED_FIELDS = {"id", "name", "filename", "caption", "rarity"}

    def __init__(self, database: Database, catalog_path: Path, images_dir: Path) -> None:
        self.database = database
        self.catalog_path = catalog_path
        self.images_dir = images_dir
        self._rng = random.SystemRandom()
        self._catalog: dict[str, Collectible] = {}

    @property
    def enabled_count(self) -> int:
        """Return the number of enabled catalog entries."""

        return len(self.enabled_ids)

    @property
    def enabled_ids(self) -> frozenset[str]:
        """Return IDs currently enabled in the JSON catalog."""

        return frozenset(
            item.collectible_id for item in self._catalog.values() if item.is_enabled
        )

    def image_path(self, collectible: Collectible) -> Path:
        """Return the expected local image path for a collectible."""

        return self.images_dir / collectible.filename

    async def synchronize(self) -> None:
        """Validate JSON and upsert catalog entries without deleting history."""

        if not self.catalog_path.exists():
            raise CatalogError(f"Collectible catalog not found: {self.catalog_path}")
        try:
            raw: Any = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError(f"Invalid collectible catalog: {exc}") from exc
        if not isinstance(raw, list) or not raw:
            raise CatalogError("collectibles.json must contain a non-empty JSON array")

        parsed: dict[str, Collectible] = {}
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise CatalogError(f"Catalog item {index} must be an object")
            missing = self.REQUIRED_FIELDS - set(item)
            if missing:
                raise CatalogError(
                    f"Catalog item {index} is missing fields: {', '.join(sorted(missing))}"
                )
            non_string = [
                key for key in self.REQUIRED_FIELDS if not isinstance(item[key], str)
            ]
            if non_string:
                raise CatalogError(
                    f"Catalog item {index} fields must be strings: "
                    f"{', '.join(sorted(non_string))}"
                )
            values = {key: item[key].strip() for key in self.REQUIRED_FIELDS}
            if not all(values.values()):
                raise CatalogError(f"Catalog item {index} contains an empty required field")
            collectible_id = values["id"]
            if collectible_id in parsed:
                raise CatalogError(f"Duplicate collectible id: {collectible_id}")
            filename = values["filename"]
            if Path(filename).name != filename:
                raise CatalogError(f"Unsafe filename for {collectible_id}: {filename}")
            enabled = item.get("enabled", True)
            if not isinstance(enabled, bool):
                raise CatalogError(f"Catalog item {index} field 'enabled' must be boolean")
            parsed[collectible_id] = Collectible(
                collectible_id=collectible_id,
                name=values["name"],
                filename=filename,
                caption=values["caption"],
                description=str(item.get("description", "")).strip(),
                rarity=values["rarity"],
                is_enabled=enabled,
            )

        async with self.database.transaction() as connection:
            await connection.execute("UPDATE collectibles SET is_enabled = 0")
            for collectible in parsed.values():
                await connection.execute(
                    """
                    INSERT INTO collectibles(
                        collectible_id, name, filename, caption,
                        description, rarity, is_enabled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(collectible_id) DO UPDATE SET
                        name = excluded.name,
                        filename = excluded.filename,
                        caption = excluded.caption,
                        description = excluded.description,
                        rarity = excluded.rarity,
                        is_enabled = excluded.is_enabled
                    """,
                    (
                        collectible.collectible_id,
                        collectible.name,
                        collectible.filename,
                        collectible.caption,
                        collectible.description,
                        collectible.rarity,
                        int(collectible.is_enabled),
                    ),
                )
        self._catalog = parsed
        missing_images = [
            item.filename
            for item in parsed.values()
            if item.is_enabled and not self.image_path(item).is_file()
        ]
        if missing_images:
            LOGGER.warning(
                "Some enabled collectibles have no image and will be skipped",
                extra={"missing_image_count": len(missing_images)},
            )

    async def get(self, collectible_id: str) -> Collectible | None:
        """Return an item from the in-memory catalog or SQLite fallback."""

        cached = self._catalog.get(collectible_id)
        if cached is not None:
            return cached
        row = await self.database.fetchone(
            "SELECT * FROM collectibles WHERE collectible_id = ?", (collectible_id,)
        )
        if row is None:
            return None
        return Collectible(
            collectible_id=str(row["collectible_id"]),
            name=str(row["name"]),
            filename=str(row["filename"]),
            caption=str(row["caption"]),
            description=str(row["description"]),
            rarity=str(row["rarity"]),
            is_enabled=bool(row["is_enabled"]),
        )

    def choose(self, previous_id: str | None = None) -> Collectible | None:
        """Choose a random enabled item with an existing image.

        When at least two valid items exist, the immediately previous item is excluded.
        """

        valid = [
            item
            for item in self._catalog.values()
            if item.is_enabled and self.image_path(item).is_file()
        ]
        if not valid:
            return None
        candidates = [item for item in valid if item.collectible_id != previous_id]
        return self._rng.choice(candidates or valid)
