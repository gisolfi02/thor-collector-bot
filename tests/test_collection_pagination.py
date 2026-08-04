from app.views.collection_pagination import can_control_collection


def test_pagination_cannot_be_controlled_by_other_users() -> None:
    assert can_control_collection(100, 100)
    assert not can_control_collection(100, 101)
