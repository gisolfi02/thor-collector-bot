from dataclasses import dataclass

from app.services.spawn_manager import missing_channel_permissions


@dataclass
class FakePermissions:
    view_channel: bool = True
    send_messages: bool = True
    embed_links: bool = True
    attach_files: bool = True
    read_message_history: bool = True


class FakeChannel:
    def __init__(self, permissions: FakePermissions) -> None:
        self.permissions = permissions

    def permissions_for(self, member):
        return self.permissions


def test_missing_permissions_are_reported_precisely() -> None:
    channel = FakeChannel(FakePermissions(send_messages=False, attach_files=False))
    missing = missing_channel_permissions(channel, object())
    assert missing == ["Send Messages", "Attach Files"]
