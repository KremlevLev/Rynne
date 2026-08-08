# modules/brain/model_gateway.py
from __future__ import annotations

import asyncio
import copy
import logging
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from openai import AsyncOpenAI

import core.config as config
from modules.brain.model_router import ModelCandidate


logger = logging.getLogger("ModelGateway")


GROQ_API_KEYS: tuple[str, ...] = tuple(
    getattr(config, "GROQ_API_KEYS", ())
)

OPENROUTER_API_KEYS: tuple[str, ...] = tuple(
    getattr(config, "OPENROUTER_API_KEYS", ())
)

GEMINI_API_KEYS: tuple[str, ...] = tuple(
    getattr(config, "GEMINI_API_KEYS", ())
)
GROQ_KEY_MODELS: tuple[str, ...] = tuple(getattr(config, "GROQ_KEY_MODELS", ()))
OPENROUTER_KEY_MODELS: tuple[str, ...] = tuple(
    getattr(config, "OPENROUTER_KEY_MODELS", ())
)
GEMINI_KEY_MODELS: tuple[str, ...] = tuple(getattr(config, "GEMINI_KEY_MODELS", ()))

GROQ_BASE_URL = getattr(
    config,
    "GROQ_BASE_URL",
    "https://api.groq.com/openai/v1",
)

OPENROUTER_BASE_URL = getattr(
    config,
    "OPENROUTER_BASE_URL",
    "https://openrouter.ai/api/v1",
)

GEMINI_BASE_URL = getattr(
    config,
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
)

GEMINI_QUOTA_GROUP = getattr(
    config,
    "GEMINI_QUOTA_GROUP",
    "gemini-project-main",
)

LLM_REQUEST_TIMEOUT = float(
    getattr(config, "LLM_REQUEST_TIMEOUT", 90.0)
)

GROQ_RATE_LIMIT_COOLDOWN = float(
    getattr(config, "GROQ_RATE_LIMIT_COOLDOWN", 90.0)
)

PROVIDER_ERROR_COOLDOWN = float(
    getattr(config, "PROVIDER_ERROR_COOLDOWN", 30.0)
)

DAILY_LIMIT_COOLDOWN = float(
    getattr(config, "DAILY_LIMIT_COOLDOWN", 21600.0)
)


class FailureKind(StrEnum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    DAILY_LIMIT = "daily_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    SERVER = "server"
    CONTEXT = "context"
    BAD_REQUEST = "bad_request"
    TOOL_PROTOCOL = "tool_protocol"
    EMPTY_RESPONSE = "empty_response"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class GatewayFailure(Exception):
    kind: FailureKind
    message: str
    retryable: bool = False
    cooldown_seconds: float = 0.0
    status_code: int | None = None

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class KeySlot:
    provider: str
    index: int
    api_key: str
    quota_group: str | None = None
    model_override: str | None = None

    # Только глобальное состояние ключа.
    disabled: bool = False
    global_cooldown_until: float = 0.0

    consecutive_failures: int = 0
    successful_requests: int = 0
    in_flight_requests: int = 0

    last_error: str | None = None
    last_success_at: float | None = None

    @property
    def label(self) -> str:
        # Значение ключа никогда не выводится в лог.
        group_suffix = f"-{self.quota_group}" if self.quota_group else ""
        return f"{self.provider}-key-{self.index + 1}{group_suffix}"

    @property
    def globally_available(self) -> bool:
        return (
            not self.disabled
            and time.monotonic()
            >= self.global_cooldown_until
        )

    @property
    def global_cooldown_remaining(self) -> float:
        return max(
            0.0,
            self.global_cooldown_until
            - time.monotonic(),
        )

    def disable(self, reason: str) -> None:
        self.disabled = True
        self.last_error = reason
        self.consecutive_failures += 1

    def start_global_cooldown(
        self,
        seconds: float,
        reason: str,
    ) -> None:
        self.global_cooldown_until = max(
            self.global_cooldown_until,
            time.monotonic() + max(0.0, seconds),
        )
        self.last_error = reason
        self.consecutive_failures += 1

    def mark_failure(self, reason: str) -> None:
        self.last_error = reason
        self.consecutive_failures += 1

    def mark_success(self) -> None:
        self.consecutive_failures = 0
        self.last_error = None
        self.successful_requests += 1
        self.last_success_at = time.time()


@dataclass(slots=True)
class ModelResponse:
    provider: str
    model: str
    key_label: str
    text: str
    tool_calls: list[dict[str, Any]]

    finish_reason: str | None = None
    usage: dict[str, Any] = field(
        default_factory=dict
    )


class ModelGateway:
    """
    Мультипровайдерный шлюз Nova.

    Уровни блокировки:

    1. Ключ целиком:
       - 401;
       - 403;
       - суточная или общая квота.

    2. Сочетание ключ + модель:
       - обычный 429;
       - краткосрочный TPM/RPM;
       - timeout конкретного маршрута;
       - пустой ответ.

    3. Модель у провайдера:
       - модель не поддерживает protocol/tools;
       - некорректный формат запроса;
       - временная ошибка самой модели.

    4. Провайдер:
       - очевидная общая сетевая недоступность.
    """

    def __init__(self) -> None:
        # Определяем группы квот для каждого провайдера
        gemini_quota_groups: dict[int, str] = {}
        if GEMINI_QUOTA_GROUP:
            for index, _ in enumerate(GEMINI_API_KEYS):
                gemini_quota_groups[index] = GEMINI_QUOTA_GROUP

        self._key_slots: dict[str, list[KeySlot]] = {
            "groq": [
                KeySlot(
                    provider="groq",
                    index=index,
                    api_key=api_key,
                    model_override=(GROQ_KEY_MODELS[index] or None)
                    if index < len(GROQ_KEY_MODELS)
                    else None,
                )
                for index, api_key in enumerate(
                    GROQ_API_KEYS
                )
            ],
            "openrouter": [
                KeySlot(
                    provider="openrouter",
                    index=index,
                    api_key=api_key,
                    model_override=(OPENROUTER_KEY_MODELS[index] or None)
                    if index < len(OPENROUTER_KEY_MODELS)
                    else None,
                )
                for index, api_key in enumerate(
                    OPENROUTER_API_KEYS
                )
            ],
            "gemini": [
                KeySlot(
                    provider="gemini",
                    index=index,
                    api_key=api_key,
                    quota_group=gemini_quota_groups.get(index),
                    model_override=(GEMINI_KEY_MODELS[index] or None)
                    if index < len(GEMINI_KEY_MODELS)
                    else None,
                )
                for index, api_key in enumerate(
                    GEMINI_API_KEYS
                )
            ],
        }

        self._clients: dict[
            tuple[str, int],
            AsyncOpenAI,
        ] = {}

        self._preferred_key_index: dict[str, int] = {
            "groq": 0,
            "openrouter": 0,
            "gemini": 0,
        }

        # Cooldown конкретного маршрута:
        # provider + key index + model.
        self._route_cooldowns: dict[
            tuple[str, int, str],
            float,
        ] = {}

        # Cooldown модели независимо от ключа.
        self._model_cooldowns: dict[
            tuple[str, str],
            float,
        ] = {}

        # Cooldown провайдера целиком.
        self._provider_cooldowns: dict[
            str,
            float,
        ] = {}

        # Cooldown группы квоты (provider + quota_group).
        self._quota_group_cooldowns: dict[
            tuple[str, str],
            float,
        ] = {}

    async def close(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()

        await _gather_client_closes(clients)

    @staticmethod
    def _base_url(provider: str) -> str:
        if provider == "groq":
            return GROQ_BASE_URL

        if provider == "openrouter":
            return OPENROUTER_BASE_URL

        if provider == "gemini":
            return GEMINI_BASE_URL

        raise ValueError(
            f"Неизвестный провайдер: {provider}"
        )

    def _get_client(
        self,
        slot: KeySlot,
    ) -> AsyncOpenAI:
        client_identity = (
            slot.provider,
            slot.index,
        )

        existing_client = self._clients.get(
            client_identity
        )

        if existing_client is not None:
            return existing_client

        client = AsyncOpenAI(
            base_url=self._base_url(slot.provider),
            api_key=slot.api_key,
            timeout=LLM_REQUEST_TIMEOUT,

            # SDK не должен ждать на одном ключе.
            # Ротацией управляет ModelGateway.
            max_retries=0,
        )

        self._clients[client_identity] = client
        return client

    def _ordered_slots(
        self,
        provider: str,
    ) -> list[KeySlot]:
        slots = self._key_slots.get(provider, [])

        if not slots:
            return []

        preferred_index = (
            self._preferred_key_index.get(
                provider,
                0,
            )
        )

        preferred_index %= len(slots)

        rotated = (
            slots[preferred_index:]
            + slots[:preferred_index]
        )
        # Concurrent subagents should spread over independent keys instead of
        # all hitting the last successful slot and sharing its RPM/TPM bucket.
        return sorted(
            rotated,
            key=lambda slot: slot.in_flight_requests,
        )

    def _set_preferred_key(
        self,
        slot: KeySlot,
    ) -> None:
        self._preferred_key_index[
            slot.provider
        ] = slot.index

    @staticmethod
    def _route_identity(
        slot: KeySlot,
        candidate: ModelCandidate,
    ) -> tuple[str, int, str]:
        return (
            slot.provider,
            slot.index,
            candidate.model,
        )

    @staticmethod
    def _model_identity(
        candidate: ModelCandidate,
    ) -> tuple[str, str]:
        return (
            candidate.provider,
            candidate.model,
        )

    def _quota_group_identity(
        self,
        slot: KeySlot,
    ) -> tuple[str, str] | None:
        """Возвращает идентификатор группы квоты если key имеет quota_group."""
        if slot.quota_group:
            return (slot.provider, slot.quota_group)
        return None

    def _quota_group_cooldown_remaining(
        self,
        slot: KeySlot,
    ) -> float:
        """Возвращает оставшееся время cooldown группы квоты."""
        identity = self._quota_group_identity(slot)
        if not identity:
            return 0.0

        cooldown_until = self._quota_group_cooldowns.get(
            identity,
            0.0,
        )
        return max(0.0, cooldown_until - time.monotonic())

    def _set_quota_group_cooldown(
        self,
        slot: KeySlot,
        seconds: float,
    ) -> None:
        """Ставит cooldown на всю группу квоты."""
        identity = self._quota_group_identity(slot)
        if not identity or seconds <= 0:
            return

        self._quota_group_cooldowns[identity] = max(
            self._quota_group_cooldowns.get(identity, 0.0),
            time.monotonic() + seconds,
        )
        logger.info(
            "Группа квоты %s поставлена на cooldown %.0f сек.",
            identity[1],
            seconds,
        )

    def _route_cooldown_remaining(
        self,
        slot: KeySlot,
        candidate: ModelCandidate,
    ) -> float:
        cooldown_until = self._route_cooldowns.get(
            self._route_identity(
                slot,
                candidate,
            ),
            0.0,
        )

        return max(
            0.0,
            cooldown_until - time.monotonic(),
        )

    def _model_cooldown_remaining(
        self,
        candidate: ModelCandidate,
    ) -> float:
        cooldown_until = self._model_cooldowns.get(
            self._model_identity(candidate),
            0.0,
        )

        return max(
            0.0,
            cooldown_until - time.monotonic(),
        )

    def _provider_cooldown_remaining(
        self,
        provider: str,
    ) -> float:
        cooldown_until = self._provider_cooldowns.get(
            provider,
            0.0,
        )

        return max(
            0.0,
            cooldown_until - time.monotonic(),
        )

    def _set_route_cooldown(
        self,
        slot: KeySlot,
        candidate: ModelCandidate,
        seconds: float,
    ) -> None:
        if seconds <= 0:
            return

        identity = self._route_identity(
            slot,
            candidate,
        )

        self._route_cooldowns[identity] = max(
            self._route_cooldowns.get(
                identity,
                0.0,
            ),
            time.monotonic() + seconds,
        )

        logger.info(
            "Маршрут %s/%s поставлен на cooldown %.0f сек.",
            slot.label,
            candidate.model,
            seconds,
        )

    def _set_model_cooldown(
        self,
        candidate: ModelCandidate,
        seconds: float,
    ) -> None:
        if seconds <= 0:
            return

        identity = self._model_identity(candidate)

        self._model_cooldowns[identity] = max(
            self._model_cooldowns.get(
                identity,
                0.0,
            ),
            time.monotonic() + seconds,
        )

        logger.info(
            "Модель %s:%s поставлена на cooldown %.0f сек.",
            candidate.provider,
            candidate.model,
            seconds,
        )

    def _set_provider_cooldown(
        self,
        provider: str,
        seconds: float,
    ) -> None:
        if seconds <= 0:
            return

        self._provider_cooldowns[provider] = max(
            self._provider_cooldowns.get(
                provider,
                0.0,
            ),
            time.monotonic() + seconds,
        )

        logger.info(
            "Провайдер %s поставлен на cooldown %.0f сек.",
            provider,
            seconds,
        )

    def _clear_route_cooldown(
        self,
        slot: KeySlot,
        candidate: ModelCandidate,
    ) -> None:
        self._route_cooldowns.pop(
            self._route_identity(slot, candidate),
            None,
        )

    @staticmethod
    def _extract_status_code(
        error: Exception,
    ) -> int | None:
        direct_status = getattr(
            error,
            "status_code",
            None,
        )

        if isinstance(direct_status, int):
            return direct_status

        response = getattr(error, "response", None)
        response_status = getattr(
            response,
            "status_code",
            None,
        )

        if isinstance(response_status, int):
            return response_status

        return None

    @staticmethod
    def _extract_retry_after(
        error: Exception,
    ) -> float | None:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)

        if not headers:
            return None

        raw_value = (
            headers.get("retry-after")
            or headers.get("Retry-After")
        )

        if not raw_value:
            return None

        try:
            return max(
                1.0,
                float(raw_value),
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def classify_failure(
        cls,
        error: Exception,
    ) -> GatewayFailure:
        if isinstance(error, GatewayFailure):
            return error

        raw_message = str(error)
        lowered = raw_message.lower()

        status_code = cls._extract_status_code(
            error
        )
        retry_after = cls._extract_retry_after(
            error
        )

        if status_code in {401, 403} or any(
            marker in lowered
            for marker in (
                "invalid api key",
                "incorrect api key",
                "invalid_api_key",
                "authentication",
                "unauthorized",
                "forbidden",
            )
        ):
            return GatewayFailure(
                kind=FailureKind.AUTHENTICATION,
                message="Ключ провайдера отклонен.",
                retryable=False,
                status_code=status_code,
            )

        daily_markers = (
            "daily limit",
            "daily quota",
            "per day",
            "tokens per day",
            "requests per day",
            "daily tokens",
            "quota exceeded",
            "insufficient_quota",
            "rpd",
            "tpd",
        )

        if any(
            marker in lowered
            for marker in daily_markers
        ):
            return GatewayFailure(
                kind=FailureKind.DAILY_LIMIT,
                message=(
                    "Достигнут суточный или общий "
                    "лимит API-ключа."
                ),
                retryable=True,
                cooldown_seconds=DAILY_LIMIT_COOLDOWN,
                status_code=status_code,
            )

        rate_limit_markers = (
            "rate limit",
            "rate_limit",
            "too many requests",
            "limit exceeded",
            "requests per minute",
            "tokens per minute",
            "rpm",
            "tpm",
        )

        if (
            status_code == 429
            or any(
                marker in lowered
                for marker in rate_limit_markers
            )
        ):
            return GatewayFailure(
                kind=FailureKind.RATE_LIMIT,
                message=(
                    "Достигнут краткосрочный лимит "
                    "этого модельного маршрута."
                ),
                retryable=True,
                cooldown_seconds=(
                    retry_after
                    or GROQ_RATE_LIMIT_COOLDOWN
                ),
                status_code=status_code,
            )

        tool_protocol_markers = (
            "tool call validation failed",
            "parameters for tool",
            "did not match schema",
            "additionalproperties",
            "tool choice is none",
            "model called a tool",
        )

        if any(
            marker in lowered
            for marker in tool_protocol_markers
        ):
            return GatewayFailure(
                kind=FailureKind.TOOL_PROTOCOL,
                message=(
                    "Модель нарушила протокол вызова "
                    "инструментов."
                ),
                retryable=True,
                cooldown_seconds=15.0,
                status_code=status_code,
            )

        context_markers = (
            "context_length",
            "context length",
            "maximum context",
            "too many tokens",
            "context window",
        )

        if any(
            marker in lowered
            for marker in context_markers
        ):
            return GatewayFailure(
                kind=FailureKind.CONTEXT,
                message=(
                    "Контекст превысил лимит модели."
                ),
                retryable=False,
                status_code=status_code,
            )

        if status_code in {500, 502, 503, 504}:
            return GatewayFailure(
                kind=FailureKind.SERVER,
                message=(
                    "Провайдер или модель временно "
                    f"недоступны: HTTP {status_code}."
                ),
                retryable=True,
                cooldown_seconds=PROVIDER_ERROR_COOLDOWN,
                status_code=status_code,
            )

        timeout_markers = (
            "timeout",
            "timed out",
            "read timeout",
            "connect timeout",
        )

        if any(
            marker in lowered
            for marker in timeout_markers
        ):
            return GatewayFailure(
                kind=FailureKind.TIMEOUT,
                message=(
                    "Превышено время ожидания модели."
                ),
                retryable=True,
                cooldown_seconds=10.0,
                status_code=status_code,
            )

        connection_markers = (
            "connection error",
            "connection failed",
            "network error",
            "dns error",
            "name resolution",
        )

        if any(
            marker in lowered
            for marker in connection_markers
        ):
            return GatewayFailure(
                kind=FailureKind.CONNECTION,
                message=(
                    "Ошибка соединения с провайдером."
                ),
                retryable=True,
                cooldown_seconds=5.0,
                status_code=status_code,
            )

        if status_code == 400:
            return GatewayFailure(
                kind=FailureKind.BAD_REQUEST,
                message=(
                    "Провайдер отклонил формат запроса: "
                    f"{raw_message}"
                ),
                retryable=False,
                cooldown_seconds=10.0,
                status_code=status_code,
            )

        return GatewayFailure(
            kind=FailureKind.UNKNOWN,
            message=(
                "Неизвестная ошибка модельного маршрута: "
                f"{raw_message}"
            ),
            retryable=True,
            cooldown_seconds=10.0,
            status_code=status_code,
        )

    @staticmethod
    def _prepare_tools_for_provider(
        tools: list[dict[str, Any]] | None,
        provider: str,
    ) -> list[dict[str, Any]] | None:
        """
        Для Groq удаляет additionalProperties из передаваемой схемы.

        Строгая локальная валидация остается в ToolRunner. Это не
        снижает безопасность, но предотвращает отклонение всего
        ответа из-за фантомных параметров некоторых моделей.
        """
        if not tools:
            return None

        prepared_tools = copy.deepcopy(tools)

        if provider != "groq":
            return prepared_tools

        def relax_schema(value: Any) -> None:
            if isinstance(value, dict):
                value.pop(
                    "additionalProperties",
                    None,
                )

                for child in value.values():
                    relax_schema(child)

            elif isinstance(value, list):
                for child in value:
                    relax_schema(child)

        for tool in prepared_tools:
            parameters = (
                tool.get("function", {})
                .get("parameters")
            )
            relax_schema(parameters)

        return prepared_tools

    @staticmethod
    def _consume_tool_call_delta(
        target: dict[int, dict[str, Any]],
        delta_tool_calls: Any,
    ) -> None:
        for tool_call in delta_tool_calls or []:
            tool_index = int(tool_call.index)

            if tool_index not in target:
                target[tool_index] = {
                    "id": tool_call.id or "",
                    "type": "function",
                    "function": {
                        "name": "",
                        "arguments": "",
                    },
                }

            current_call = target[tool_index]

            if tool_call.id:
                current_call["id"] = tool_call.id

            function_delta = getattr(
                tool_call,
                "function",
                None,
            )

            if function_delta is None:
                continue

            if function_delta.name:
                current_call["function"]["name"] += (
                    function_delta.name
                )

            if function_delta.arguments:
                current_call["function"]["arguments"] += (
                    function_delta.arguments
                )

    async def _request_once(
        self,
        *,
        slot: KeySlot,
        candidate: ModelCandidate,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        allow_tools: bool,
    ) -> ModelResponse:
        client = self._get_client(slot)

        request_arguments: dict[str, Any] = {
            "model": candidate.model,
            "messages": messages,
            "stream": True,
        }

        prepared_tools = (
            self._prepare_tools_for_provider(
                tools,
                candidate.provider,
            )
        )

        if (
            allow_tools
            and prepared_tools
            and candidate.supports_tools
        ):
            request_arguments["tools"] = (
                prepared_tools
            )
            request_arguments["tool_choice"] = "auto"

        if candidate.provider == "openrouter":
            request_arguments["extra_headers"] = {
                "HTTP-Referer": (
                    "https://localhost/nova"
                ),
                "X-Title": "Nova Windows Assistant",
            }

            request_arguments["extra_body"] = {
                "provider": {
                    "allow_fallbacks": True,
                }
            }

        if candidate.provider == "gemini":
            # Gemini не требует extra_headers, но можно добавить если нужно
            pass

        stream = await (
            client.chat.completions.create(
                **request_arguments
            )
        )

        text_parts: list[str] = []
        accumulated_tool_calls: dict[
            int,
            dict[str, Any],
        ] = {}

        finish_reason: str | None = None
        usage: dict[str, Any] = {}

        async for chunk in stream:
            chunk_usage = getattr(
                chunk,
                "usage",
                None,
            )

            if chunk_usage is not None:
                if hasattr(
                    chunk_usage,
                    "model_dump",
                ):
                    usage = chunk_usage.model_dump()

            if not chunk.choices:
                continue

            choice = chunk.choices[0]

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            delta = choice.delta

            if delta.content:
                text_parts.append(delta.content)

            self._consume_tool_call_delta(
                accumulated_tool_calls,
                delta.tool_calls,
            )

        response_text = "".join(
            text_parts
        ).strip()

        response_tool_calls = list(
            accumulated_tool_calls.values()
        )

        if (
            not response_text
            and not response_tool_calls
        ):
            raise GatewayFailure(
                kind=FailureKind.EMPTY_RESPONSE,
                message="Модель вернула пустой ответ.",
                retryable=True,
                cooldown_seconds=10.0,
            )

        return ModelResponse(
            provider=candidate.provider,
            model=candidate.model,
            key_label=slot.label,
            text=response_text,
            tool_calls=response_tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    def _register_failure(
        self,
        *,
        slot: KeySlot,
        candidate: ModelCandidate,
        failure: GatewayFailure,
    ) -> None:
        """
        Назначает cooldown правильному уровню.
        """
        if failure.kind == FailureKind.AUTHENTICATION:
            slot.disable(failure.message)
            return

        if failure.kind == FailureKind.DAILY_LIMIT:
            slot.start_global_cooldown(
                failure.cooldown_seconds,
                failure.message,
            )
            # Также ставим cooldown на группу квоты если есть
            self._set_quota_group_cooldown(
                slot,
                failure.cooldown_seconds,
            )
            return

        slot.mark_failure(failure.message)

        if failure.kind == FailureKind.RATE_LIMIT:
            # Блокируется только ключ + модель.
            self._set_route_cooldown(
                slot,
                candidate,
                failure.cooldown_seconds,
            )
            return

        if failure.kind in {
            FailureKind.TIMEOUT,
            FailureKind.EMPTY_RESPONSE,
        }:
            # Проблема конкретного маршрута.
            self._set_route_cooldown(
                slot,
                candidate,
                failure.cooldown_seconds,
            )
            return

        if failure.kind in {
            FailureKind.TOOL_PROTOCOL,
            FailureKind.BAD_REQUEST,
            FailureKind.CONTEXT,
        }:
            # Другой ключ той же модели обычно не поможет.
            self._set_model_cooldown(
                candidate,
                failure.cooldown_seconds,
            )
            return

        if failure.kind == FailureKind.SERVER:
            # Не блокируем весь провайдер: другая модель может работать.
            self._set_model_cooldown(
                candidate,
                failure.cooldown_seconds,
            )
            return

        if failure.kind == FailureKind.CONNECTION:
            self._set_provider_cooldown(
                candidate.provider,
                failure.cooldown_seconds,
            )
            return

        self._set_route_cooldown(
            slot,
            candidate,
            failure.cooldown_seconds,
        )

    @staticmethod
    def _should_try_next_key(
        failure: GatewayFailure,
    ) -> bool:
        return failure.kind in {
            FailureKind.AUTHENTICATION,
            FailureKind.DAILY_LIMIT,
            FailureKind.RATE_LIMIT,
            FailureKind.TIMEOUT,
            FailureKind.EMPTY_RESPONSE,
        }

    async def complete(
        self,
        *,
        candidates: list[ModelCandidate],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        allow_tools: bool = True,
        requires_vision: bool = False,
    ) -> ModelResponse:
        failure_messages: list[str] = []
        attempted_routes: set[tuple[str, int, str]] = set()

        for candidate in candidates:
            if (
                requires_vision
                and not candidate.supports_vision
            ):
                failure_messages.append(
                    (
                        f"{candidate.identity}: "
                        "модель не поддерживает vision"
                    )
                )
                continue

            provider_cooldown = (
                self._provider_cooldown_remaining(
                    candidate.provider
                )
            )

            if provider_cooldown > 0:
                logger.info(
                    "Провайдер %s пропущен, cooldown %.0f сек.",
                    candidate.provider,
                    provider_cooldown,
                )

                failure_messages.append(
                    (
                        f"{candidate.identity}: провайдер "
                        f"на cooldown {provider_cooldown:.0f} сек."
                    )
                )
                continue

            slots = self._ordered_slots(
                candidate.provider
            )

            if not slots:
                failure_messages.append(
                    (
                        f"{candidate.identity}: "
                        "API-ключи отсутствуют"
                    )
                )
                continue

            usable_route_found = False
            move_to_next_candidate = False

            for slot in slots:
                effective_candidate = (
                    replace(candidate, model=slot.model_override)
                    if slot.model_override
                    else candidate
                )
                route_identity = (
                    effective_candidate.provider,
                    slot.index,
                    effective_candidate.model,
                )
                if route_identity in attempted_routes:
                    continue
                attempted_routes.add(route_identity)

                if not slot.globally_available:
                    logger.info(
                        "%s пропущен: disabled=%s, "
                        "global cooldown=%.0f сек.",
                        slot.label,
                        slot.disabled,
                        slot.global_cooldown_remaining,
                    )

                    failure_messages.append(
                        (
                            f"{candidate.identity}/"
                            f"{slot.label}: ключ недоступен"
                        )
                    )
                    continue

                model_cooldown = self._model_cooldown_remaining(effective_candidate)
                if model_cooldown > 0:
                    failure_messages.append(
                        f"{effective_candidate.identity}: модель на cooldown "
                        f"{model_cooldown:.0f} сек."
                    )
                    continue

                # Проверяем quota group cooldown
                quota_group_cooldown = self._quota_group_cooldown_remaining(slot)
                if quota_group_cooldown > 0:
                    logger.info(
                        "%s пропущен: quota group cooldown %.0f сек.",
                        slot.label,
                        quota_group_cooldown,
                    )
                    failure_messages.append(
                        f"{candidate.identity}/{slot.label}: quota group cooldown {quota_group_cooldown:.0f} сек."
                    )
                    continue

                route_cooldown = (
                    self._route_cooldown_remaining(
                        slot,
                        effective_candidate,
                    )
                )

                if route_cooldown > 0:
                    logger.info(
                        "%s/%s пропущен, route cooldown %.0f сек.",
                        slot.label,
                        effective_candidate.model,
                        route_cooldown,
                    )

                    failure_messages.append(
                        (
                            f"{effective_candidate.identity}/"
                            f"{slot.label}: route cooldown "
                            f"{route_cooldown:.0f} сек."
                        )
                    )
                    continue

                usable_route_found = True

                logger.info(
                    "Запрос: provider=%s model=%s key=%s",
                    effective_candidate.provider,
                    effective_candidate.model,
                    slot.label,
                )

                try:
                    slot.in_flight_requests += 1
                    response = await self._request_once(
                        slot=slot,
                        candidate=effective_candidate,
                        messages=messages,
                        tools=tools,
                        allow_tools=allow_tools,
                    )

                except Exception as error:
                    failure = self.classify_failure(
                        error
                    )

                    self._register_failure(
                        slot=slot,
                        candidate=effective_candidate,
                        failure=failure,
                    )

                    failure_description = (
                        f"{effective_candidate.identity}/"
                        f"{slot.label}: "
                        f"{failure.message}"
                    )

                    failure_messages.append(
                        failure_description
                    )

                    logger.warning(
                        "Сбой %s на %s: %s",
                        effective_candidate.identity,
                        slot.label,
                        failure.message,
                    )

                    if self._should_try_next_key(
                        failure
                    ):
                        # Следующий ключ той же модели.
                        continue

                    # Ошибка относится к модели или провайдеру.
                    move_to_next_candidate = True
                    break

                else:
                    slot.mark_success()
                    self._set_preferred_key(slot)
                    self._clear_route_cooldown(
                        slot,
                        effective_candidate,
                    )

                    logger.info(
                        "Успешный ответ: provider=%s "
                        "model=%s key=%s finish=%s",
                        response.provider,
                        response.model,
                        response.key_label,
                        response.finish_reason,
                    )

                    return response
                finally:
                    slot.in_flight_requests = max(
                        0,
                        slot.in_flight_requests - 1,
                    )

            if not usable_route_found:
                failure_messages.append(
                    (
                        f"{candidate.identity}: "
                        "нет доступных маршрутов"
                    )
                )

            if move_to_next_candidate:
                continue

        error_details = " | ".join(
            failure_messages
        )

        raise RuntimeError(
            "Ни один модельный маршрут не сработал. "
            + error_details
        )

    def health_snapshot(
        self,
    ) -> dict[str, Any]:
        key_states: list[dict[str, Any]] = []

        for provider, slots in self._key_slots.items():
            for slot in slots:
                key_states.append(
                    {
                        "provider": provider,
                        "index": slot.index,
                        "key": slot.label,
                        "model_override": slot.model_override or "",
                        "available": (
                            slot.globally_available
                        ),
                        "disabled": slot.disabled,
                        "global_cooldown_seconds": round(
                            slot.global_cooldown_remaining,
                            1,
                        ),
                        "successful_requests": (
                            slot.successful_requests
                        ),
                        "in_flight_requests": slot.in_flight_requests,
                        "consecutive_failures": (
                            slot.consecutive_failures
                        ),
                        "last_error": slot.last_error,
                        "last_success_at": (
                            slot.last_success_at
                        ),
                        "quota_group": slot.quota_group,
                    }
                )

        route_states: list[dict[str, Any]] = []
        current_monotonic = time.monotonic()

        for (
            provider,
            key_index,
            model,
        ), cooldown_until in self._route_cooldowns.items():
            remaining = max(
                0.0,
                cooldown_until
                - current_monotonic,
            )

            if remaining <= 0:
                continue

            route_states.append(
                {
                    "provider": provider,
                    "key": (
                        f"{provider}-key-{key_index + 1}"
                    ),
                    "model": model,
                    "cooldown_seconds": round(
                        remaining,
                        1,
                    ),
                }
            )

        model_states: list[dict[str, Any]] = []

        for (
            provider,
            model,
        ), cooldown_until in self._model_cooldowns.items():
            remaining = max(
                0.0,
                cooldown_until
                - current_monotonic,
            )

            if remaining <= 0:
                continue

            model_states.append(
                {
                    "provider": provider,
                    "model": model,
                    "cooldown_seconds": round(
                        remaining,
                        1,
                    ),
                }
            )

        provider_states: list[dict[str, Any]] = []

        for (
            provider,
            cooldown_until,
        ) in self._provider_cooldowns.items():
            remaining = max(
                0.0,
                cooldown_until
                - current_monotonic,
            )

            if remaining <= 0:
                continue

            provider_states.append(
                {
                    "provider": provider,
                    "cooldown_seconds": round(
                        remaining,
                        1,
                    ),
                }
            )

        quota_group_states: list[dict[str, Any]] = []

        for (
            provider,
            quota_group,
        ), cooldown_until in self._quota_group_cooldowns.items():
            remaining = max(
                0.0,
                cooldown_until
                - current_monotonic,
            )

            if remaining <= 0:
                continue

            quota_group_states.append(
                {
                    "provider": provider,
                    "quota_group": quota_group,
                    "cooldown_seconds": round(
                        remaining,
                        1,
                    ),
                }
            )

        provider_capacity: dict[str, dict[str, int]] = {}
        independent_lanes: set[tuple[str, str]] = set()
        total_in_flight = 0
        for item in key_states:
            provider = str(item["provider"])
            stats = provider_capacity.setdefault(
                provider,
                {"total": 0, "available": 0, "in_flight": 0},
            )
            stats["total"] += 1
            stats["in_flight"] += int(item["in_flight_requests"])
            total_in_flight += int(item["in_flight_requests"])
            if item["available"]:
                stats["available"] += 1
                quota_group = str(item.get("quota_group") or item["key"])
                independent_lanes.add((provider, quota_group))

        return {
            "keys": key_states,
            "routes": route_states,
            "models": model_states,
            "providers": provider_states,
            "quota_groups": quota_group_states,
            "capacity": {
                "providers": provider_capacity,
                "total_keys": len(key_states),
                "available_keys": sum(
                    1 for item in key_states if item["available"]
                ),
                "parallel_lanes": len(independent_lanes),
                "in_flight": total_in_flight,
            },
        }


async def _gather_client_closes(
    clients: list[AsyncOpenAI],
) -> None:
    if not clients:
        return

    await asyncio.gather(
        *(
            client.close()
            for client in clients
        ),
        return_exceptions=True,
    )
