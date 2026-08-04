from app.services.capture_service import is_capture_text


def test_thor_is_recognized() -> None:
    assert is_capture_text("thor")


def test_uppercase_thor_is_recognized() -> None:
    assert is_capture_text("THOR")


def test_outer_spaces_are_ignored() -> None:
    assert is_capture_text("  ThOr  ")


def test_punctuation_is_rejected() -> None:
    assert not is_capture_text("thor!")


def test_sentence_containing_thor_is_rejected() -> None:
    assert not is_capture_text("io catturo thor")
