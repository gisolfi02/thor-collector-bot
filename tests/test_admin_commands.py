from app.cogs.game_commands import can_manage_game, validate_spawn_interval


def test_changetime_rejects_invalid_values() -> None:
    assert validate_spawn_interval(0, 10) is not None
    assert validate_spawn_interval(90, 30) is not None
    assert validate_spawn_interval(1, 10_081) is not None
    assert validate_spawn_interval(10, 10) is None


def test_non_admin_cannot_use_changetime() -> None:
    assert not can_manage_game(100, 200)


def test_non_admin_cannot_use_destroy() -> None:
    assert not can_manage_game(100, 201)
