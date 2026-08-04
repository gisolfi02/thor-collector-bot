import json
from pathlib import Path

import pytest

from app.services.collectible_service import CollectibleService


@pytest.mark.asyncio
async def test_missing_image_does_not_crash_bot(database, tmp_path: Path) -> None:
    catalog = tmp_path / "collectibles.json"
    images = tmp_path / "collectibles"
    images.mkdir()
    catalog.write_text(
        json.dumps(
            [
                {
                    "id": "thor_missing",
                    "name": "Thor Mancante",
                    "filename": "missing.jpg",
                    "caption": "Un Thor è apparso!",
                    "rarity": "Raro",
                    "description": "Immagine intenzionalmente assente.",
                }
            ]
        ),
        encoding="utf-8",
    )
    service = CollectibleService(database, catalog, images)
    await service.synchronize()
    assert service.choose() is None
