# tests/test_desktop_bridge.py
from __future__ import annotations

import asyncio

from modules.domain.results import ToolResult
from modules.tools.permissions import (
    PermissionManager,
)
from modules.ui.core_bridge import (
    CoreDesktopBridge,
)
from modules.ui.desktop_protocol import (
    make_command,
)
from modules.input_hub.models import (
    UserRequest,
)


class FakeDesktop:
    def __init__(self) -> None:
        self.events = []

    def publish(
        self,
        event_type,
        payload=None,
    ):
        self.events.append(
            {
                "event_type": event_type,
                "payload": payload or {},
            }
        )
        return True

    def get_commands(self):
        return []



class FakeProcessManager:
    def __init__(self) -> None:
        self.stopped = []

    def list_processes(self):
        return ToolResult.ok(
            "Список.",
            data={
                "processes": [],
            },
        )

    def stop_process(
        self,
        process_id,
        force=False,
    ):
        self.stopped.append(
            (process_id, force)
        )

        return ToolResult.ok(
            "Остановлен."
        )


class FakeMemoryStore:
    def __init__(self) -> None:
        self.deleted = []
        self.cleared = False

    def search(
        self,
        query,
        limit=200,
    ):
        return [
            {
                "key": "name",
                "value": "Nova",
                "category": "test",
                "confidence": 1.0,
            }
        ]

    def delete(self, key):
        self.deleted.append(key)
        return True

    def clear_all(self):
        self.cleared = True
        return True


class FakeLLM:
    def provider_health(self):
        return {
            "keys": [],
            "local": {
                "llm_configured": False,
            },
        }


class FakeState:
    value = "СПИТ"


class FakeRuntime:
    state = FakeState()
    is_active = False
    is_shutting_down = False


def create_bridge():
    desktop = FakeDesktop()
    process_manager = FakeProcessManager()
    memory_store = FakeMemoryStore()

    bridge = CoreDesktopBridge(
        desktop=desktop,
        process_manager=process_manager,
        memory_store=memory_store,
        permission_manager=(
            PermissionManager()
        ),
        llm=FakeLLM(),
        runtime=FakeRuntime(),
    )

    return (
        bridge,
        desktop,
        process_manager,
        memory_store,
    )


def test_manual_proactive_check_triggers_callback() -> None:
    async def scenario() -> None:
        desktop = FakeDesktop()
        requested: list[bool] = []
        bridge = CoreDesktopBridge(
            desktop=desktop,
            process_manager=FakeProcessManager(),
            memory_store=FakeMemoryStore(),
            permission_manager=PermissionManager(),
            llm=FakeLLM(),
            runtime=FakeRuntime(),
            request_proactive_check=lambda: requested.append(True),
        )
        await bridge.handle_command(make_command("run_proactive_check"))
        assert requested == [True]
        assert desktop.events[-1]["payload"]["success"] is True

    asyncio.run(scenario())


def test_publish_snapshots() -> None:
    async def scenario() -> None:
        (
            bridge,
            desktop,
            _,
            _,
        ) = create_bridge()

        await bridge.publish_snapshots()

        event_types = {
            event["event_type"]
            for event in desktop.events
        }

        assert "runtime" in event_types
        assert "processes" in event_types
        assert "memories" in event_types
        assert "permissions" in event_types
        assert "models" in event_types

    asyncio.run(scenario())


def test_stop_process_command() -> None:
    async def scenario() -> None:
        (
            bridge,
            desktop,
            process_manager,
            _,
        ) = create_bridge()

        command = make_command(
            "stop_process",
            {
                "process_id": "proc-1",
                "force": True,
            },
        )

        await bridge.handle_command(
            command
        )

        assert process_manager.stopped == [
            ("proc-1", True)
        ]

        assert desktop.events[-1][
            "event_type"
        ] == "command_result"

    asyncio.run(scenario())


def test_delete_memory_command() -> None:
    async def scenario() -> None:
        (
            bridge,
            _,
            _,
            memory_store,
        ) = create_bridge()

        command = make_command(
            "delete_memory",
            {
                "key": "name",
            },
        )

        await bridge.handle_command(
            command
        )

        assert memory_store.deleted == [
            "name"
        ]

    asyncio.run(scenario())


def test_unknown_command_returns_error() -> None:
    async def scenario() -> None:
        (
            bridge,
            desktop,
            _,
            _,
        ) = create_bridge()

        command = make_command(
            "unknown_action"
        )

        await bridge.handle_command(
            command
        )

        result_event = desktop.events[-1]

        assert (
            result_event["event_type"]
            == "command_result"
        )
        assert not result_event[
            "payload"
        ]["success"]

    asyncio.run(scenario())
class FakeInputCoordinator:
    def __init__(self) -> None:
        self.requests = []

    async def submit_text(
        self,
        text,
        **kwargs,
    ):
        request = UserRequest.from_text(
            text,
            **{
                key: value
                for key, value in kwargs.items()
                if key in {
                    "source",
                    "profile",
                    "model_mode",
                    "selected_model",
                    "metadata",
                    "attachments",
                }
            },
        )

        self.requests.append(request)
        return request
def test_submit_user_request_command() -> None:
    async def scenario() -> None:
        (
            bridge,
            desktop,
            _,
            _,
        ) = create_bridge()

        coordinator = (
            FakeInputCoordinator()
        )

        bridge.input_coordinator = (
            coordinator
        )

        command = make_command(
            "submit_user_request",
            {
                "text": "Который час?",
                "profile": "assistant",
                "model_mode": "auto",
            },
        )

        await bridge.handle_command(
            command
        )

        assert len(
            coordinator.requests
        ) == 1

        assert (
            coordinator.requests[0].text
            == "Который час?"
        )

        assert (
            desktop.events[-1][
                "event_type"
            ]
            == "command_result"
        )

    asyncio.run(scenario())
class FakeModeManager:
    def __init__(self) -> None:
        self.modes = []

    async def set_mode_from_string(
        self,
        mode_name,
    ):
        from modules.application.preferences import (
            PreferencesManager,
        )
        from modules.input_hub.models import (
            InputMode,
        )

        self.modes.append(mode_name)

        preferences = PreferencesManager()

        return preferences.set_input_mode(
            InputMode(mode_name)
        )

    async def toggle_manual_voice(self):
        from modules.application.preferences import (
            PreferencesManager,
        )
        from modules.input_hub.models import (
            InputMode,
        )

        preferences = PreferencesManager()
        snapshot = preferences.set_input_mode(
            InputMode.CONTINUOUS
        )
        return True, snapshot


def test_set_input_mode_command() -> None:
    async def scenario() -> None:
        (
            bridge,
            desktop,
            _,
            _,
        ) = create_bridge()

        mode_manager = FakeModeManager()
        bridge.mode_manager = mode_manager

        command = make_command(
            "set_input_mode",
            {
                "input_mode": "text_only",
            },
        )

        await bridge.handle_command(
            command
        )

        assert mode_manager.modes == [
            "text_only"
        ]

        assert any(
            event["event_type"]
            == "preferences"
            for event in desktop.events
        )

    asyncio.run(scenario())


def test_toggle_voice_publishes_actual_input_mode() -> None:
    async def scenario() -> None:
        bridge, desktop, _, _ = create_bridge()
        bridge.mode_manager = FakeModeManager()

        await bridge.handle_command(
            make_command("toggle_voice_mode")
        )

        preference_events = [
            event
            for event in desktop.events
            if event["event_type"] == "preferences"
        ]
        assert preference_events[-1]["payload"][
            "input_mode"
        ] == "continuous"
        assert desktop.events[-1]["event_type"] == (
            "command_result"
        )
        assert desktop.events[-1]["payload"][
            "success"
        ] is True

    asyncio.run(scenario())


def test_proactive_acceptance_is_marked_on_request() -> None:
    async def scenario() -> None:
        bridge, _, _, _ = create_bridge()
        coordinator = FakeInputCoordinator()
        bridge.input_coordinator = coordinator

        await bridge.handle_command(
            make_command(
                "submit_user_request",
                {
                    "text": "Помоги заполнить форму",
                    "proactive_event_id": (
                        "proactive_visual_demo"
                    ),
                },
            )
        )

        metadata = coordinator.requests[0].metadata
        assert metadata[
            "proactive_suggestion_accepted"
        ] is True
        assert (
            metadata["proactive_event_id"]
            == "proactive_visual_demo"
        )

    asyncio.run(scenario())


def test_proactive_visual_context_becomes_ephemeral_attachment(
    tmp_path,
) -> None:
    class FakeContextStore:
        def __init__(self) -> None:
            self.keys = []

        def materialize_once(self, source_key):
            self.keys.append(source_key)
            path = tmp_path / "context.jpg"
            path.write_bytes(b"jpeg")
            return str(path)

    async def scenario() -> None:
        bridge, _, _, _ = create_bridge()
        coordinator = FakeInputCoordinator()
        context_store = FakeContextStore()
        bridge.input_coordinator = coordinator
        bridge.proactive_context_store = context_store

        await bridge.handle_command(
            make_command(
                "submit_user_request",
                {
                    "text": "Разбери ошибку",
                    "proactive_event_id": (
                        "proactive_visual_demo"
                    ),
                    "proactive_context_key": (
                        "visual:fingerprint"
                    ),
                },
            )
        )

        request = coordinator.requests[0]
        assert context_store.keys == [
            "visual:fingerprint"
        ]
        assert request.has_image
        assert request.attachments[0].metadata[
            "delete_after_read"
        ] is True

    asyncio.run(scenario())


def test_enable_proactive_vision_command() -> None:
    async def scenario() -> None:
        from modules.application.preferences import (
            PreferencesManager,
        )

        bridge, desktop, _, _ = create_bridge()
        preferences = PreferencesManager()
        bridge.preferences = preferences

        await bridge.handle_command(
            make_command(
                "set_preference",
                {
                    "key": "proactive_vision_enabled",
                    "value": True,
                },
            )
        )

        assert (
            preferences.snapshot()
            .proactive_vision_enabled
        )
        preference_events = [
            event
            for event in desktop.events
            if event["event_type"] == "preferences"
        ]
        assert preference_events[-1]["payload"][
            "proactive_vision_enabled"
        ] is True

    asyncio.run(scenario())
