# modules/tools/base.py
from __future__ import annotations

import asyncio
import copy
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable


class ToolCategory(StrEnum):
    SYSTEM_READ = "system_read"
    SYSTEM_WRITE = "system_write"

    APPLICATION = "application"
    GUI_READ = "gui_read"
    GUI_WRITE = "gui_write"

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"

    MEMORY = "memory"
    REMINDER = "reminder"

    WEB_READ = "web_read"
    NETWORK_WRITE = "network_write"

    PROCESS_READ = "process_read"
    PROCESS_CONTROL = "process_control"

    TERMINAL = "terminal"
    DEVELOPMENT = "development"

    CLIPBOARD_READ = "clipboard_read"
    CLIPBOARD_WRITE = "clipboard_write"

    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    WRITE = "write"
    EXECUTE = "execute"
    DESTRUCTIVE = "destructive"
    CRITICAL = "critical"


@dataclass(slots=True)
class ToolCancellationToken:
    """
    Кооперативная отмена.

    Старые синхронные инструменты пока не используют токен,
    но новые долгие skills смогут регулярно проверять:
        context.cancellation.raise_if_cancelled()
    """

    _event: asyncio.Event = field(
        default_factory=asyncio.Event
    )

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise asyncio.CancelledError(
                "Операция инструмента отменена."
            )


@dataclass(slots=True)
class ToolContext:
    operation_id: str
    session_id: str
    turn_id: str

    working_directory: Path
    started_at_monotonic: float

    expected_window: str | None = None
    source: str = "assistant"

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    cancellation: ToolCancellationToken = field(
        default_factory=ToolCancellationToken
    )

    @classmethod
    def create(
        cls,
        *,
        session_id: str = "default-session",
        turn_id: str = "default-turn",
        working_directory: str | Path | None = None,
        expected_window: str | None = None,
        source: str = "assistant",
        metadata: dict[str, Any] | None = None,
    ) -> "ToolContext":
        resolved_working_directory = Path(
            working_directory or os.getcwd()
        ).resolve()

        return cls(
            operation_id=(
                f"operation_{uuid.uuid4().hex}"
            ),
            session_id=session_id,
            turn_id=turn_id,
            working_directory=(
                resolved_working_directory
            ),
            started_at_monotonic=time.monotonic(),
            expected_window=expected_window,
            source=source,
            metadata=metadata or {},
        )

    @property
    def elapsed_ms(self) -> int:
        return max(
            0,
            round(
                (
                    time.monotonic()
                    - self.started_at_monotonic
                )
                * 1000
            ),
        )


@dataclass(slots=True)
class ToolDefinition:
    """
    Единое описание инструмента.

    Из одной структуры runtime получает:
    - OpenAI JSON Schema;
    - handler;
    - уровень риска;
    - категорию;
    - timeout;
    - свойства идемпотентности;
    - поддержку rollback;
    - необходимость ToolContext.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]

    category: ToolCategory = ToolCategory.UNKNOWN
    risk: RiskLevel = RiskLevel.LOW

    timeout_seconds: float = 30.0

    idempotent: bool = False
    supports_rollback: bool = False
    requires_confirmation: bool = False

    # Новый handler может принимать:
    # handler(context=context, **arguments)
    inject_context: bool = False

    # Rollback metadata for recovery
    rollback_info: dict[str, Any] | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "Имя инструмента не может быть пустым."
            )

        if not callable(self.handler):
            raise TypeError(
                f"Handler инструмента '{self.name}' "
                "не является callable."
            )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "Timeout инструмента должен быть больше нуля."
            )

        self.parameters.setdefault(
            "type",
            "object",
        )
        self.parameters.setdefault(
            "properties",
            {},
        )
        self.parameters.setdefault(
            "additionalProperties",
            False,
        )

    @classmethod
    def from_legacy(
        cls,
        *,
        schema: dict[str, Any],
        handler: Callable[..., Any],
        category: ToolCategory = ToolCategory.UNKNOWN,
        risk: RiskLevel = RiskLevel.LOW,
        timeout_seconds: float = 30.0,
        idempotent: bool = False,
        supports_rollback: bool = False,
        requires_confirmation: bool = False,
    ) -> "ToolDefinition":
        function_schema = schema.get(
            "function",
            {},
        )

        name = function_schema.get("name")
        description = function_schema.get(
            "description",
            "",
        )
        parameters = copy.deepcopy(
            function_schema.get(
                "parameters",
                {
                    "type": "object",
                    "properties": {},
                },
            )
        )

        if not isinstance(name, str) or not name:
            raise ValueError(
                "Legacy-схема не содержит имя инструмента."
            )

        return cls(
            name=name,
            description=str(description),
            parameters=parameters,
            handler=handler,
            category=category,
            risk=risk,
            timeout_seconds=timeout_seconds,
            idempotent=idempotent,
            supports_rollback=supports_rollback,
            requires_confirmation=(
                requires_confirmation
            ),
            inject_context=False,
            metadata={
                "legacy_adapter": True,
            },
        )

    def to_openai_schema(
        self,
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": copy.deepcopy(
                    self.parameters
                ),
            },
        }

    @property
    def schema(self) -> dict[str, Any]:
        """
        Совместимость со старым runtime, который обращался к
        registered_tool.schema.
        """
        return self.to_openai_schema()


# Совместимость со старыми импортами.
RegisteredTool = ToolDefinition
