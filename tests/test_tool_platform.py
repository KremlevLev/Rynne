# tests/test_tool_platform.py
from __future__ import annotations

import asyncio
import json

from modules.domain.results import (
    ToolResult,
    VerificationResult,
)
from modules.tools.base import (
    RiskLevel,
    ToolCategory,
    ToolContext,
    ToolDefinition,
)
from modules.tools.runtime import (
    ToolRegistry,
    ToolRunner,
)


def create_tool_call(
    name: str,
    arguments: dict,
) -> dict:
    return {
        "id": "test_call_1",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(
                arguments,
                ensure_ascii=False,
            ),
        },
    }


def test_tool_result_serialization() -> None:
    result = ToolResult.ok(
        "Операция выполнена.",
        data={
            "value": 42,
        },
        duration_ms=150,
        rollback_token="rollback_123",
        verification=VerificationResult(
            verified=True,
            method="readback",
            confidence=1.0,
            details="Результат прочитан обратно.",
        ),
    )

    serialized = result.to_dict()

    assert serialized["success"] is True
    assert serialized["code"] == "OK"
    assert serialized["data"]["value"] == 42
    assert serialized["duration_ms"] == 150
    assert (
        serialized["rollback_token"]
        == "rollback_123"
    )
    assert (
        serialized["verification"]["verified"]
        is True
    )

    model_content = json.loads(
        result.to_model_content()
    )

    assert model_content["success"] is True
    assert model_content["data"]["value"] == 42


def test_verification_confidence_is_clamped() -> None:
    verification = VerificationResult(
        verified=True,
        method="test",
        confidence=5.0,
    )

    assert (
        verification.to_dict()["confidence"]
        == 1.0
    )


def test_tool_context_has_unique_operation_id() -> None:
    first = ToolContext.create(
        session_id="session-1",
        turn_id="turn-1",
    )
    second = ToolContext.create(
        session_id="session-1",
        turn_id="turn-1",
    )

    assert first.operation_id != second.operation_id
    assert first.session_id == "session-1"
    assert first.turn_id == "turn-1"
    assert first.working_directory.is_absolute()


def test_tool_context_cancellation() -> None:
    context = ToolContext.create()

    assert not context.cancellation.is_cancelled

    context.cancellation.cancel()

    assert context.cancellation.is_cancelled


def test_definition_generates_openai_schema() -> None:
    def handler(text: str) -> str:
        return text

    definition = ToolDefinition(
        name="echo",
        description="Возвращает текст.",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                }
            },
            "required": ["text"],
        },
        handler=handler,
        category=ToolCategory.SYSTEM_READ,
        risk=RiskLevel.READ_ONLY,
        idempotent=True,
    )

    schema = definition.to_openai_schema()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    assert (
        schema["function"]["parameters"]
        ["additionalProperties"]
        is False
    )


def test_registry_accepts_definition() -> None:
    registry = ToolRegistry()

    definition = ToolDefinition(
        name="read_value",
        description="Читает значение.",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=lambda: "value",
        category=ToolCategory.SYSTEM_READ,
        risk=RiskLevel.READ_ONLY,
        idempotent=True,
    )

    registry.register_definition(definition)

    assert registry.get("read_value") is definition
    assert "read_value" in registry.names
    assert (
        registry.schemas()[0]["function"]["name"]
        == "read_value"
    )


def test_registry_resolves_case_and_separator_drift_without_guessing() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(
        name="open_application",
        description="Opens an app.",
        parameters={"type": "object", "properties": {}},
        handler=lambda: "ok",
        category=ToolCategory.SYSTEM_WRITE,
        risk=RiskLevel.LOW,
        idempotent=False,
    )
    registry.register_definition(definition)

    assert registry.resolve_name("OpenApplication") == "open_application"
    assert registry.resolve_name("OPEN-APPLICATION") == "open_application"
    assert registry.get("OpenApplication") is definition


def test_registry_resolves_unique_mcp_service_suffix() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(
        name="mcp_telegram_business_send_message",
        description="Sends a Telegram message.",
        parameters={"type": "object", "properties": {}},
        handler=lambda: "ok",
        category=ToolCategory.NETWORK_WRITE,
        risk=RiskLevel.EXECUTE,
        idempotent=False,
    )
    registry.register_definition(definition)

    assert (
        registry.resolve_name("telegram_send_message")
        == "mcp_telegram_business_send_message"
    )


def test_registry_rejects_duplicate_definition() -> None:
    registry = ToolRegistry()

    definition = ToolDefinition(
        name="duplicate",
        description="Тест.",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=lambda: "ok",
    )

    registry.register_definition(definition)

    try:
        registry.register_definition(definition)
    except ValueError as exc:
        assert "зарегистрирован повторно" in str(exc)
    else:
        raise AssertionError(
            "Повторная регистрация не была отклонена."
        )


def test_runner_emits_live_ui_events() -> None:
    async def scenario() -> None:
        events: list[tuple[str, dict]] = []
        registry = ToolRegistry()
        registry.register_definition(
            ToolDefinition(
                name="echo_live",
                description="Проверяет live events.",
                parameters={
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                    },
                    "required": ["value"],
                },
                handler=lambda value: ToolResult.ok(value),
                category=ToolCategory.SYSTEM_READ,
                risk=RiskLevel.READ_ONLY,
                idempotent=True,
            )
        )
        runner = ToolRunner(
            registry,
            event_sink=lambda event_type, payload: events.append(
                (event_type, payload)
            ),
        )

        result = await runner.execute(
            create_tool_call("echo_live", {"value": "ok"})
        )

        assert result.success is True
        assert [event_type for event_type, _ in events] == [
            "tool_started",
            "tool_completed",
        ]
        assert events[0][1]["tool_name"] == "echo_live"
        assert events[1][1]["success"] is True
        assert (
            events[0][1]["operation_id"]
            == events[1][1]["operation_id"]
        )

    asyncio.run(scenario())


def test_runner_executes_context_aware_tool() -> None:
    async def scenario() -> None:
        received_operation_ids: list[str] = []

        def handler(
            *,
            context: ToolContext,
            value: int,
        ) -> ToolResult:
            received_operation_ids.append(
                context.operation_id
            )

            return ToolResult.ok(
                "Значение обработано.",
                data={
                    "value": value * 2,
                },
                verification=VerificationResult(
                    verified=True,
                    method="calculation",
                    confidence=1.0,
                ),
            )

        registry = ToolRegistry()

        registry.register_definition(
            ToolDefinition(
                name="double_value",
                description="Удваивает число.",
                parameters={
                    "type": "object",
                    "properties": {
                        "value": {
                            "type": "integer",
                        }
                    },
                    "required": ["value"],
                },
                handler=handler,
                category=ToolCategory.SYSTEM_READ,
                risk=RiskLevel.READ_ONLY,
                inject_context=True,
                idempotent=True,
            )
        )

        runner = ToolRunner(registry)

        context = ToolContext.create(
            session_id="session-test",
            turn_id="turn-test",
        )

        result = await runner.execute(
            create_tool_call(
                "double_value",
                {
                    "value": 21,
                },
            ),
            context=context,
        )

        assert result.success
        assert result.data["value"] == 42
        assert (
            result.data["operation_id"]
            == context.operation_id
        )
        assert (
            result.data["session_id"]
            == "session-test"
        )
        assert (
            result.data["turn_id"]
            == "turn-test"
        )
        assert received_operation_ids == [
            context.operation_id
        ]

    asyncio.run(scenario())


def test_runner_removes_unknown_arguments() -> None:
    async def scenario() -> None:
        received_arguments: list[str] = []

        def handler(text: str) -> str:
            received_arguments.append(text)
            return "Готово."

        registry = ToolRegistry()

        registry.register_definition(
            ToolDefinition(
                name="safe_text",
                description="Принимает текст.",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                        }
                    },
                    "required": ["text"],
                },
                handler=handler,
            )
        )

        runner = ToolRunner(registry)

        result = await runner.execute(
            create_tool_call(
                "safe_text",
                {
                    "text": "Тест",
                    "phantom": "удалить меня",
                },
            )
        )

        assert result.success
        assert received_arguments == ["Тест"]
        assert result.warnings
        assert (
            result.warnings[0].code
            == "UNKNOWN_ARGUMENTS_REMOVED"
        )

    asyncio.run(scenario())


def test_runner_rejects_missing_required_parameter() -> None:
    async def scenario() -> None:
        handler_called = False

        def handler(text: str) -> str:
            nonlocal handler_called
            handler_called = True
            return text

        registry = ToolRegistry()

        registry.register_definition(
            ToolDefinition(
                name="required_text",
                description="Требует текст.",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                        }
                    },
                    "required": ["text"],
                },
                handler=handler,
            )
        )

        runner = ToolRunner(registry)

        result = await runner.execute(
            create_tool_call(
                "required_text",
                {},
            )
        )

        assert not result.success
        assert (
            result.code
            == "ARGUMENT_VALIDATION_FAILED"
        )
        assert not handler_called

    asyncio.run(scenario())


def test_runner_normalizes_application_argument_alias() -> None:
    async def scenario() -> None:
        received: list[str] = []

        def handler(app_name: str) -> str:
            received.append(app_name)
            return "ok"

        registry = ToolRegistry()
        registry.register_definition(
            ToolDefinition(
                name="open_application",
                description="Open an application.",
                parameters={
                    "type": "object",
                    "properties": {"app_name": {"type": "string"}},
                    "required": ["app_name"],
                },
                handler=handler,
            )
        )

        result = await ToolRunner(registry).execute(
            create_tool_call(
                "open_application",
                {"application": "Obsidian"},
            )
        )

        assert result.success
        assert received == ["Obsidian"]

    asyncio.run(scenario())


def test_runner_propagates_task_cancellation() -> None:
    async def scenario() -> None:
        started = asyncio.Event()

        async def handler() -> str:
            started.set()
            await asyncio.Event().wait()
            return "unreachable"

        registry = ToolRegistry()
        registry.register_definition(
            ToolDefinition(
                name="long_tool",
                description="Long operation.",
                parameters={"type": "object", "properties": {}},
                handler=handler,
            )
        )
        task = asyncio.create_task(
            ToolRunner(registry).execute(create_tool_call("long_tool", {}))
        )
        await started.wait()
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("Tool cancellation must propagate to RequestService")

    asyncio.run(scenario())


def test_runner_adapts_legacy_string_result() -> None:
    async def scenario() -> None:
        registry = ToolRegistry()

        registry.register_definition(
            ToolDefinition(
                name="legacy_tool",
                description="Legacy tool.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                handler=lambda: "Успешный результат.",
            )
        )

        runner = ToolRunner(registry)

        result = await runner.execute(
            create_tool_call(
                "legacy_tool",
                {},
            )
        )

        assert result.success
        assert result.message == "Успешный результат."
        assert result.duration_ms is not None
        assert (
            result.verification.verified
            is None
        )

    asyncio.run(scenario())


def test_runner_adapts_legacy_error_string() -> None:
    async def scenario() -> None:
        registry = ToolRegistry()

        registry.register_definition(
            ToolDefinition(
                name="legacy_error",
                description="Legacy error.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                handler=lambda: (
                    "Ошибка: действие не выполнено."
                ),
            )
        )

        runner = ToolRunner(registry)

        result = await runner.execute(
            create_tool_call(
                "legacy_error",
                {},
            )
        )

        assert not result.success
        assert result.code == "LEGACY_TOOL_ERROR"

    asyncio.run(scenario())
