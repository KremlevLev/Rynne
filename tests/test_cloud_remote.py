import pytest

from modules.integrations.cloud_remote import CloudRemoteConfig, CloudRemoteError, RynneCloudRemoteClient


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse(self.responses.pop(0))


def make_client(responses: list[dict]) -> tuple[RynneCloudRemoteClient, FakeSession]:
    session = FakeSession(responses)
    remote = RynneCloudRemoteClient(
        CloudRemoteConfig("https://cloud.example", "pc", "device-secret-123456"),
        session=session,
    )
    return remote, session


def test_configuration_requires_https_and_long_token() -> None:
    assert not CloudRemoteConfig("http://local", "pc", "short").configured
    assert CloudRemoteConfig("https://cloud.example", "pc", "long-device-token-1").configured


def test_heartbeat_uses_bearer_device_credential() -> None:
    remote, session = make_client([{"ok": True}])
    remote.heartbeat(name="Lev laptop", version="1.0.0", status="idle")
    assert session.calls[0]["url"].endswith("/v1/devices/pc/heartbeat")
    assert session.calls[0]["headers"]["Authorization"] == "Bearer device-secret-123456"


def test_claim_and_complete_remote_task() -> None:
    remote, session = make_client([
        {"task": {"task_id": "abc", "text": "Open Obsidian"}},
        {"ok": True},
    ])
    task = remote.next_task()
    remote.event(task["task_id"], "completed", result="Done")
    assert task["text"] == "Open Obsidian"
    assert session.calls[1]["json"]["result"] == "Done"


def test_cloud_wake_signal_is_polled_separately_from_tasks() -> None:
    remote, session = make_client([{"wake": True}])
    assert remote.next_wake() is True
    assert session.calls[0]["url"].endswith("/v1/devices/pc/wake/next")


def test_unconfigured_client_fails_without_network() -> None:
    with pytest.raises(CloudRemoteError):
        RynneCloudRemoteClient(CloudRemoteConfig()).next_task()
