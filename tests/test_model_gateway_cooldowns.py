# tests/test_model_gateway_cooldowns.py
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import modules.brain.model_gateway as gateway_module
from modules.brain.model_gateway import (
    FailureKind,
    GatewayFailure,
    KeySlot,
    ModelGateway,
    ModelResponse,
    is_internal_control_label,
)
from modules.brain.model_router import ModelCandidate


def test_internal_control_labels_are_not_user_answers() -> None:
    assert is_internal_control_label("User Safety: safe")
    assert is_internal_control_label("classification: allowed")
    assert not is_internal_control_label("This action is safe to continue.")


def create_candidate(
    model: str,
    *,
    provider: str = "openrouter",
) -> ModelCandidate:
    return ModelCandidate(
        provider=provider,
        model=model,
        supports_tools=True,
        supports_vision=False,
        priority=10,
    )


def test_managed_route_reads_regular_completion_instead_of_stream(
    monkeypatch,
) -> None:
    gateway = ModelGateway()
    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(
                                name="open_application",
                                arguments='{"app_name":"telegram"}',
                            ),
                        )],
                    ),
                    finish_reason="tool_calls",
                )],
                usage=SimpleNamespace(
                    model_dump=lambda: {"total_tokens": 42},
                ),
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=FakeCompletions(),
        ),
    )
    monkeypatch.setattr(gateway, "_get_client", lambda _slot: client)

    response = asyncio.run(gateway._request_once(
        slot=KeySlot(provider="managed", index=0, api_key="trial-token"),
        candidate=create_candidate(
            "openai/gpt-oss-120b",
            provider="managed",
        ),
        messages=[{"role": "user", "content": "open telegram"}],
        tools=[{
            "type": "function",
            "function": {
                "name": "open_application",
                "description": "Open an application",
                "parameters": {
                    "type": "object",
                    "properties": {"app_name": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
        }],
        allow_tools=True,
    ))

    assert captured["stream"] is False
    assert response.text == ""
    assert response.tool_calls == [{
        "id": "call-1",
        "type": "function",
        "function": {
            "name": "open_application",
            "arguments": '{"app_name":"telegram"}',
        },
    }]
    assert response.usage == {"total_tokens": 42}
    assert "additionalProperties" not in (
        captured["tools"][0]["function"]["parameters"]
    )


def test_managed_tool_schema_relaxation_does_not_mutate_registry() -> None:
    tools = [{
        "type": "function",
        "function": {
            "name": "example",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
            },
        },
    }]

    prepared = ModelGateway._prepare_tools_for_provider(tools, "managed")

    assert "additionalProperties" not in prepared[0]["function"]["parameters"]
    assert tools[0]["function"]["parameters"]["additionalProperties"] is False


def test_managed_route_reads_regular_text_completion(monkeypatch) -> None:
    gateway = ModelGateway()

    class FakeCompletions:
        async def create(self, **kwargs):
            assert kwargs["stream"] is False
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(
                        content="Короткий ответ.",
                        tool_calls=None,
                    ),
                    finish_reason="stop",
                )],
                usage=None,
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    monkeypatch.setattr(gateway, "_get_client", lambda _slot: client)

    response = asyncio.run(gateway._request_once(
        slot=KeySlot(provider="managed", index=0, api_key="trial-token"),
        candidate=create_candidate(
            "openai/gpt-oss-120b",
            provider="managed",
        ),
        messages=[{"role": "user", "content": "Что произошло?"}],
        tools=None,
        allow_tools=False,
    ))

    assert response.text == "Короткий ответ."
    assert response.tool_calls == []


def test_rate_limit_blocks_only_route() -> None:
    gateway = ModelGateway()

    slot = KeySlot(
        provider="openrouter",
        index=0,
        api_key="test-key",
    )

    first_model = create_candidate("model-a")
    second_model = create_candidate("model-b")

    failure = GatewayFailure(
        kind=FailureKind.RATE_LIMIT,
        message="Краткосрочный лимит.",
        retryable=True,
        cooldown_seconds=60,
        status_code=429,
    )

    gateway._register_failure(
        slot=slot,
        candidate=first_model,
        failure=failure,
    )

    assert slot.globally_available

    assert (
        gateway._route_cooldown_remaining(
            slot,
            first_model,
        )
        > 0
    )

    assert (
        gateway._route_cooldown_remaining(
            slot,
            second_model,
        )
        == 0
    )


def test_authentication_disables_entire_key() -> None:
    gateway = ModelGateway()

    slot = KeySlot(
        provider="groq",
        index=0,
        api_key="invalid-key",
    )

    candidate = create_candidate(
        "model-a",
        provider="groq",
    )

    failure = GatewayFailure(
        kind=FailureKind.AUTHENTICATION,
        message="Неверный ключ.",
        retryable=False,
        status_code=401,
    )

    gateway._register_failure(
        slot=slot,
        candidate=candidate,
        failure=failure,
    )

    assert slot.disabled
    assert not slot.globally_available


def test_daily_limit_blocks_entire_key() -> None:
    gateway = ModelGateway()

    slot = KeySlot(
        provider="groq",
        index=0,
        api_key="test-key",
    )

    candidate = create_candidate(
        "model-a",
        provider="groq",
    )

    failure = GatewayFailure(
        kind=FailureKind.DAILY_LIMIT,
        message="Суточный лимит.",
        retryable=True,
        cooldown_seconds=3600,
        status_code=429,
    )

    gateway._register_failure(
        slot=slot,
        candidate=candidate,
        failure=failure,
    )

    assert not slot.globally_available
    assert slot.global_cooldown_remaining > 3500


def test_same_key_uses_second_model_after_429(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        gateway = ModelGateway()

        gateway._key_slots = {
            "groq": [],
            "openrouter": [
                KeySlot(
                    provider="openrouter",
                    index=0,
                    api_key="test-key",
                )
            ],
        }

        first_model = create_candidate(
            "model-a"
        )
        second_model = create_candidate(
            "model-b"
        )

        calls: list[str] = []

        async def fake_request_once(
            *,
            slot,
            candidate,
            messages,
            tools,
            allow_tools,
        ):
            calls.append(candidate.model)

            if candidate.model == "model-a":
                raise GatewayFailure(
                    kind=FailureKind.RATE_LIMIT,
                    message="429",
                    retryable=True,
                    cooldown_seconds=60,
                    status_code=429,
                )

            return ModelResponse(
                provider=candidate.provider,
                model=candidate.model,
                key_label=slot.label,
                text="Успешный ответ.",
                tool_calls=[],
                finish_reason="stop",
            )

        monkeypatch.setattr(
            gateway,
            "_request_once",
            fake_request_once,
        )

        response = await gateway.complete(
            candidates=[
                first_model,
                second_model,
            ],
            messages=[
                {
                    "role": "user",
                    "content": "Тест",
                }
            ],
        )

        assert calls == [
            "model-a",
            "model-b",
        ]

        assert response.model == "model-b"

        assert (
    gateway._route_cooldown_remaining(
        gateway._key_slots["openrouter"][0],
        first_model,
    )
    > 0
        )


        await gateway.close()

    asyncio.run(scenario())


def test_same_model_uses_second_key_after_429(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        gateway = ModelGateway()

        gateway._key_slots = {
            "groq": [
                KeySlot(
                    provider="groq",
                    index=0,
                    api_key="key-one",
                ),
                KeySlot(
                    provider="groq",
                    index=1,
                    api_key="key-two",
                ),
            ],
            "openrouter": [],
        }

        candidate = create_candidate(
            "model-a",
            provider="groq",
        )

        called_keys: list[str] = []

        async def fake_request_once(
            *,
            slot,
            candidate,
            messages,
            tools,
            allow_tools,
        ):
            called_keys.append(slot.label)

            if slot.index == 0:
                raise GatewayFailure(
                    kind=FailureKind.RATE_LIMIT,
                    message="429",
                    retryable=True,
                    cooldown_seconds=60,
                    status_code=429,
                )

            return ModelResponse(
                provider=candidate.provider,
                model=candidate.model,
                key_label=slot.label,
                text="Ответ второго ключа.",
                tool_calls=[],
                finish_reason="stop",
            )

        monkeypatch.setattr(
            gateway,
            "_request_once",
            fake_request_once,
        )

        response = await gateway.complete(
            candidates=[candidate],
            messages=[
                {
                    "role": "user",
                    "content": "Тест",
                }
            ],
        )

        assert called_keys == [
            "groq-key-1",
            "groq-key-2",
        ]

        assert response.key_label == "groq-key-2"

        await gateway.close()

    asyncio.run(scenario())


def test_tool_protocol_blocks_model_not_key() -> None:
    gateway = ModelGateway()

    slot = KeySlot(
        provider="groq",
        index=0,
        api_key="test-key",
    )

    candidate = create_candidate(
        "model-a",
        provider="groq",
    )

    failure = GatewayFailure(
        kind=FailureKind.TOOL_PROTOCOL,
        message="Модель нарушила протокол инструментов.",
        retryable=True,
        cooldown_seconds=15,
        status_code=400,
    )

    gateway._register_failure(
        slot=slot,
        candidate=candidate,
        failure=failure,
    )

    # Ключ остается доступен для других моделей.
    assert slot.globally_available
    assert not slot.disabled

    # Блокируется только проблемная модель у этого провайдера.
    assert (
        gateway._model_cooldown_remaining(
            candidate
        )
        > 0
    )

    # Route cooldown при tool protocol не требуется:
    # другой ключ той же модели тоже, скорее всего, не поможет.
    assert (
        gateway._route_cooldown_remaining(
            slot,
            candidate,
        )
        == 0
    )


def test_tool_protocol_does_not_block_other_model() -> None:
    gateway = ModelGateway()

    slot = KeySlot(
        provider="groq",
        index=0,
        api_key="test-key",
    )

    broken_model = create_candidate(
        "broken-tool-model",
        provider="groq",
    )

    healthy_model = create_candidate(
        "healthy-tool-model",
        provider="groq",
    )

    failure = GatewayFailure(
        kind=FailureKind.TOOL_PROTOCOL,
        message="Некорректный tool call.",
        retryable=True,
        cooldown_seconds=15,
        status_code=400,
    )

    gateway._register_failure(
        slot=slot,
        candidate=broken_model,
        failure=failure,
    )

    assert (
        gateway._model_cooldown_remaining(
            broken_model
        )
        > 0
    )

    assert (
        gateway._model_cooldown_remaining(
            healthy_model
        )
        == 0
    )

    assert slot.globally_available


def test_timeout_blocks_only_key_and_model_route() -> None:
    gateway = ModelGateway()

    first_slot = KeySlot(
        provider="groq",
        index=0,
        api_key="first-key",
    )

    second_slot = KeySlot(
        provider="groq",
        index=1,
        api_key="second-key",
    )

    candidate = create_candidate(
        "slow-model",
        provider="groq",
    )

    failure = GatewayFailure(
        kind=FailureKind.TIMEOUT,
        message="Превышено время ожидания.",
        retryable=True,
        cooldown_seconds=10,
    )

    gateway._register_failure(
        slot=first_slot,
        candidate=candidate,
        failure=failure,
    )

    assert first_slot.globally_available
    assert second_slot.globally_available

    assert (
        gateway._route_cooldown_remaining(
            first_slot,
            candidate,
        )
        > 0
    )

    # Второй ключ той же модели остается доступен.
    assert (
        gateway._route_cooldown_remaining(
            second_slot,
            candidate,
        )
        == 0
    )


def test_server_error_blocks_model_not_provider() -> None:
    gateway = ModelGateway()

    slot = KeySlot(
        provider="openrouter",
        index=0,
        api_key="test-key",
    )

    failing_model = create_candidate(
        "server-error-model",
    )

    alternative_model = create_candidate(
        "alternative-model",
    )

    failure = GatewayFailure(
        kind=FailureKind.SERVER,
        message="HTTP 503.",
        retryable=True,
        cooldown_seconds=30,
        status_code=503,
    )

    gateway._register_failure(
        slot=slot,
        candidate=failing_model,
        failure=failure,
    )

    assert slot.globally_available

    assert (
        gateway._provider_cooldown_remaining(
            "openrouter"
        )
        == 0
    )

    assert (
        gateway._model_cooldown_remaining(
            failing_model
        )
        > 0
    )

    assert (
        gateway._model_cooldown_remaining(
            alternative_model
        )
        == 0
    )


def test_connection_error_blocks_provider_temporarily() -> None:
    gateway = ModelGateway()

    slot = KeySlot(
        provider="openrouter",
        index=0,
        api_key="test-key",
    )

    candidate = create_candidate(
        "model-a",
    )

    failure = GatewayFailure(
        kind=FailureKind.CONNECTION,
        message="Сетевая ошибка.",
        retryable=True,
        cooldown_seconds=5,
    )

    gateway._register_failure(
        slot=slot,
        candidate=candidate,
        failure=failure,
    )

    assert slot.globally_available

    assert (
        gateway._provider_cooldown_remaining(
            "openrouter"
        )
        > 0
    )


def test_success_clears_route_cooldown() -> None:
    gateway = ModelGateway()

    slot = KeySlot(
        provider="groq",
        index=0,
        api_key="test-key",
    )

    candidate = create_candidate(
        "model-a",
        provider="groq",
    )

    gateway._set_route_cooldown(
        slot,
        candidate,
        60,
    )

    assert (
        gateway._route_cooldown_remaining(
            slot,
            candidate,
        )
        > 0
    )

    gateway._clear_route_cooldown(
        slot,
        candidate,
    )

    assert (
        gateway._route_cooldown_remaining(
            slot,
            candidate,
        )
        == 0
    )


def test_health_snapshot_does_not_expose_api_keys() -> None:
    gateway = ModelGateway()

    secret_value = "super-secret-api-key"

    gateway._key_slots = {
        "groq": [
            KeySlot(
                provider="groq",
                index=0,
                api_key=secret_value,
            )
        ],
        "openrouter": [],
    }

    snapshot = gateway.health_snapshot()
    serialized = str(snapshot)

    assert secret_value not in serialized
    assert "groq-key-1" in serialized


def test_health_snapshot_reports_route_cooldown() -> None:
    gateway = ModelGateway()

    slot = KeySlot(
        provider="groq",
        index=0,
        api_key="test-key",
    )

    candidate = create_candidate(
        "model-a",
        provider="groq",
    )

    gateway._key_slots = {
        "groq": [slot],
        "openrouter": [],
    }

    gateway._set_route_cooldown(
        slot,
        candidate,
        60,
    )

    snapshot = gateway.health_snapshot()

    assert snapshot["routes"]
    assert snapshot["routes"][0]["provider"] == "groq"
    assert snapshot["routes"][0]["key"] == "groq-key-1"
    assert snapshot["routes"][0]["model"] == "model-a"
    assert snapshot["routes"][0]["cooldown_seconds"] > 0


def test_classify_401_as_authentication() -> None:
    class FakeError(Exception):
        status_code = 401

    failure = ModelGateway.classify_failure(
        FakeError("Invalid API Key")
    )

    assert failure.kind == FailureKind.AUTHENTICATION
    assert not failure.retryable


def test_classify_regular_429_as_rate_limit() -> None:
    class FakeError(Exception):
        status_code = 429

    failure = ModelGateway.classify_failure(
        FakeError("Too Many Requests")
    )

    assert failure.kind == FailureKind.RATE_LIMIT
    assert failure.retryable
    assert failure.cooldown_seconds > 0


def test_classify_daily_quota_separately() -> None:
    class FakeError(Exception):
        status_code = 429

    failure = ModelGateway.classify_failure(
        FakeError(
            "Daily quota exceeded: requests per day"
        )
    )

    assert failure.kind == FailureKind.DAILY_LIMIT
    assert failure.retryable


def test_classify_tool_validation_as_protocol_error() -> None:
    failure = ModelGateway.classify_failure(
        Exception(
            "Tool call validation failed: parameters "
            "did not match schema"
        )
    )

    assert failure.kind == FailureKind.TOOL_PROTOCOL
    assert failure.retryable


def test_provider_cooldown_skips_to_another_provider(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        gateway = ModelGateway()

        gateway._key_slots = {
            "groq": [
                KeySlot(
                    provider="groq",
                    index=0,
                    api_key="groq-key",
                )
            ],
            "openrouter": [
                KeySlot(
                    provider="openrouter",
                    index=0,
                    api_key="openrouter-key",
                )
            ],
        }

        groq_candidate = create_candidate(
            "groq-model",
            provider="groq",
        )

        openrouter_candidate = create_candidate(
            "openrouter-model",
            provider="openrouter",
        )

        gateway._set_provider_cooldown(
            "groq",
            60,
        )

        calls: list[str] = []

        async def fake_request_once(
            *,
            slot,
            candidate,
            messages,
            tools,
            allow_tools,
        ):
            calls.append(candidate.identity)

            return ModelResponse(
                provider=candidate.provider,
                model=candidate.model,
                key_label=slot.label,
                text="Ответ OpenRouter.",
                tool_calls=[],
                finish_reason="stop",
            )

        monkeypatch.setattr(
            gateway,
            "_request_once",
            fake_request_once,
        )

        response = await gateway.complete(
            candidates=[
                groq_candidate,
                openrouter_candidate,
            ],
            messages=[
                {
                    "role": "user",
                    "content": "Тест",
                }
            ],
        )

        assert calls == [
            "openrouter:openrouter-model"
        ]
        assert response.provider == "openrouter"

        await gateway.close()

    asyncio.run(scenario())


def test_model_cooldown_skips_to_next_model(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        gateway = ModelGateway()

        gateway._key_slots = {
            "groq": [
                KeySlot(
                    provider="groq",
                    index=0,
                    api_key="test-key",
                )
            ],
            "openrouter": [],
        }

        first_candidate = create_candidate(
            "first-model",
            provider="groq",
        )

        second_candidate = create_candidate(
            "second-model",
            provider="groq",
        )

        gateway._set_model_cooldown(
            first_candidate,
            60,
        )

        calls: list[str] = []

        async def fake_request_once(
            *,
            slot,
            candidate,
            messages,
            tools,
            allow_tools,
        ):
            calls.append(candidate.model)

            return ModelResponse(
                provider=candidate.provider,
                model=candidate.model,
                key_label=slot.label,
                text="Успех.",
                tool_calls=[],
                finish_reason="stop",
            )

        monkeypatch.setattr(
            gateway,
            "_request_once",
            fake_request_once,
        )

        response = await gateway.complete(
            candidates=[
                first_candidate,
                second_candidate,
            ],
            messages=[
                {
                    "role": "user",
                    "content": "Тест",
                }
            ],
        )

        assert calls == ["second-model"]
        assert response.model == "second-model"

        await gateway.close()

    asyncio.run(scenario())


def test_per_key_model_override_is_used_for_request(monkeypatch) -> None:
    async def scenario() -> None:
        gateway = ModelGateway()
        gateway._key_slots = {
            "groq": [
                KeySlot(
                    provider="groq",
                    index=0,
                    api_key="test-key",
                    model_override="custom/tool-model",
                )
            ],
            "openrouter": [],
            "gemini": [],
        }
        observed: list[str] = []

        async def fake_request_once(*, slot, candidate, **_kwargs):
            observed.append(candidate.model)
            return ModelResponse(
                provider=candidate.provider,
                model=candidate.model,
                key_label=slot.label,
                text="ok",
                tool_calls=[],
            )

        monkeypatch.setattr(gateway, "_request_once", fake_request_once)
        response = await gateway.complete(
            candidates=[create_candidate("default-model", provider="groq")],
            messages=[{"role": "user", "content": "test"}],
        )

        assert observed == ["custom/tool-model"]
        assert response.model == "custom/tool-model"
        snapshot = gateway.health_snapshot()
        assert snapshot["keys"][0]["model_override"] == "custom/tool-model"
        assert snapshot["capacity"]["parallel_lanes"] == 1
        await gateway.close()

    asyncio.run(scenario())
