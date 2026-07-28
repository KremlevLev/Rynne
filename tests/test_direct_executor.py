# tests/test_direct_executor.py
from __future__ import annotations

import asyncio
from modules.application.interaction_modes import (
    InteractionModeManager,
)
from modules.domain.state import RuntimeState

from modules.application.preferences import (
    PreferencesManager,
)
from modules.domain.results import (
    ToolResult,
)
from modules.input_hub.models import (
    InputMode,
    ModelSelectionMode,
    UserRequest,
)
from modules.routing.direct_executor import (
    DirectRequestExecutor,
)
from modules.routing.intent import (
    DeterministicIntentRouter,
)
from modules.tools.base import (
    RiskLevel,
    ToolCategory,
    ToolDefinition,
)
from modules.tools.runtime import (
    ToolRegistry,
    ToolRunner,
)


def create_executor():
    calls = []

    registry = ToolRegistry()

    def open_application(
        app_name: str,
    ) -> ToolResult:
        calls.append(
            (
                "open_application",
                {
                    "app_name": app_name,
                },
            )
        )

        return ToolResult.ok(
            f"Открыто: {app_name}"
        )

    def open_application_batch(
        count: int,
    ) -> ToolResult:
        calls.append(
            (
                "open_application_batch",
                {"count": count},
            )
        )
        return ToolResult.ok(
            f"Открыто приложений: {count}"
        )

    def get_current_time():
        calls.append(
            (
                "get_current_time",
                {},
            )
        )

        return ToolResult.ok(
            "Сейчас 12:00."
        )

    def change_volume(
        action: str,
    ):
        calls.append(
            (
                "change_volume",
                {
                    "action": action,
                },
            )
        )

        return ToolResult.ok(
            f"Громкость: {action}"
        )

    registry.register_definition(
        ToolDefinition(
            name="open_application",
            description="Открывает приложение.",
            parameters={
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                    },
                },
                "required": ["app_name"],
            },
            handler=open_application,
            category=(
                ToolCategory.APPLICATION
            ),
            risk=RiskLevel.LOW,
        )
    )

    registry.register_definition(
        ToolDefinition(
            name="open_application_batch",
            description="Открывает несколько приложений.",
            parameters={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "minimum": 2,
                        "maximum": 10,
                    },
                },
                "required": ["count"],
            },
            handler=open_application_batch,
            category=ToolCategory.APPLICATION,
            risk=RiskLevel.LOW,
        )
    )

    registry.register_definition(
        ToolDefinition(
            name="get_current_time",
            description="Время.",
            parameters={
                "type": "object",
                "properties": {},
            },
            handler=get_current_time,
            category=(
                ToolCategory.SYSTEM_READ
            ),
            risk=RiskLevel.READ_ONLY,
        )
    )

    registry.register_definition(
        ToolDefinition(
            name="change_volume",
            description="Громкость.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                    },
                },
                "required": ["action"],
            },
            handler=change_volume,
            category=(
                ToolCategory.SYSTEM_WRITE
            ),
            risk=RiskLevel.LOW,
        )
    )

    preferences = PreferencesManager()

    executor = DirectRequestExecutor(
        runner=ToolRunner(registry),
        preferences=preferences,
    )

    return (
        executor,
        preferences,
        calls,
    )


def test_open_application_without_model() -> None:
    async def scenario() -> None:
        (
            executor,
            _,
            calls,
        ) = create_executor()

        request = UserRequest.from_text(
            "Открой блокнот"
        )

        decision = (
            DeterministicIntentRouter()
            .route(request)
        )

        response = await executor.execute(
            request,
            decision,
        )

        assert response.success
        assert response.data[
            "model_calls"
        ] == 0
        assert calls == [
            (
                "open_application",
                {
                    "app_name": "блокнот",
                },
            )
        ]

    asyncio.run(scenario())


def test_open_application_batch_without_model() -> None:
    async def scenario() -> None:
        executor, _, calls = create_executor()
        request = UserRequest.from_text(
            "Запусти 5-10 приложений на моём компьютере"
        )
        decision = DeterministicIntentRouter().route(request)

        response = await executor.execute(request, decision)

        assert response.success
        assert response.data["model_calls"] == 0
        assert calls == [
            (
                "open_application_batch",
                {"count": 5},
            )
        ]

    asyncio.run(scenario())


def test_time_without_model() -> None:
    async def scenario() -> None:
        (
            executor,
            _,
            calls,
        ) = create_executor()

        request = UserRequest.from_text(
            "Который час?"
        )

        decision = (
            DeterministicIntentRouter()
            .route(request)
        )

        response = await executor.execute(
            request,
            decision,
        )

        assert response.success
        assert response.data[
            "model_calls"
        ] == 0
        assert calls[0][0] == (
            "get_current_time"
        )

    asyncio.run(scenario())


def test_volume_percentage() -> None:
    async def scenario() -> None:
        (
            executor,
            _,
            calls,
        ) = create_executor()

        request = UserRequest.from_text(
            "Установи громкость на 35 процентов"
        )

        decision = (
            DeterministicIntentRouter()
            .route(request)
        )

        response = await executor.execute(
            request,
            decision,
        )

        assert response.success
        assert calls[0][1]["action"] == "35"

    asyncio.run(scenario())


def test_model_selection_without_model() -> None:
    async def scenario() -> None:
        (
            executor,
            preferences,
            _,
        ) = create_executor()

        request = UserRequest.from_text(
            "Переключись на быструю модель"
        )

        decision = (
            DeterministicIntentRouter()
            .route(request)
        )

        response = await executor.execute(
            request,
            decision,
        )

        assert response.success
        assert response.data[
            "model_calls"
        ] == 0

        assert (
            preferences.snapshot().model_mode
            == ModelSelectionMode.FAST
        )

    asyncio.run(scenario())


def test_privacy_mode_without_model() -> None:
    async def scenario() -> None:
        (
            executor,
            preferences,
            _,
        ) = create_executor()

        request = UserRequest.from_text(
            "Включи приватный режим"
        )

        decision = (
            DeterministicIntentRouter()
            .route(request)
        )

        response = await executor.execute(
            request,
            decision,
        )

        assert response.success

        snapshot = preferences.snapshot()

        assert (
            snapshot.input_mode
            == InputMode.PRIVACY
        )
        assert not snapshot.cloud_enabled
        assert not snapshot.history_enabled

    asyncio.run(scenario())
def test_mode_manager_is_used() -> None:
    async def scenario() -> None:
        (
            executor,
            preferences,
            _,
        ) = create_executor()

        runtime = RuntimeState()

        mode_manager = (
            InteractionModeManager(
                preferences=preferences,
                runtime=runtime,
            )
        )

        executor.mode_manager = mode_manager

        request = UserRequest.from_text(
            "Включи непрерывный режим"
        )

        decision = (
            DeterministicIntentRouter()
            .route(request)
        )

        response = await executor.execute(
            request,
            decision,
        )

        assert response.success
        assert runtime.is_active
        assert (
            preferences.snapshot().input_mode
            == InputMode.CONTINUOUS
        )

    asyncio.run(scenario())
