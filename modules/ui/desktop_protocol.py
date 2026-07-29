# modules/ui/desktop_protocol.py
from __future__ import annotations

import dataclasses
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


class DesktopTransport(Protocol):
    @property
    def is_running(self) -> bool:
        ...

    def start(
        self,
        *,
        premium: bool = False,
    ) -> bool:
        ...

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        ...

    def get_commands(
        self,
        *,
        max_count: int = 50,
    ) -> list[dict[str, Any]]:
        ...

    def stop(self) -> None:
        ...


def make_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_type": str(event_type),
        "payload": make_serializable(
            payload or {}
        ),
        "created_at": time.time(),
    }


def make_command(
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "command_id": (
            f"ui_command_{uuid.uuid4().hex}"
        ),
        "action": str(action),
        "payload": make_serializable(
            payload or {}
        ),
        "created_at": time.time(),
    }


def make_serializable(
    value: Any,
) -> Any:
    """
    Преобразует значение в безопасную для multiprocessing/JSON форму.
    """
    if value is None:
        return None

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Enum):
        return value.value

    if dataclasses.is_dataclass(value):
        return make_serializable(
            dataclasses.asdict(value)
        )

    if isinstance(value, dict):
        return {
            str(key): make_serializable(
                child
            )
            for key, child in value.items()
        }

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return [
            make_serializable(child)
            for child in value
        ]

    if hasattr(value, "to_dict"):
        try:
            return make_serializable(
                value.to_dict()
            )
        except Exception:
            pass

    return str(value)


def validate_command(
    command: Any,
) -> tuple[bool, str | None]:
    if not isinstance(command, dict):
        return False, "Команда UI должна быть объектом."

    if not isinstance(
        command.get("command_id"),
        str,
    ):
        return (
            False,
            "Команда UI не содержит command_id.",
        )

    if not isinstance(
        command.get("action"),
        str,
    ):
        return (
            False,
            "Команда UI не содержит action.",
        )

    payload = command.get("payload", {})

    if not isinstance(payload, dict):
        return (
            False,
            "Поле payload должно быть объектом.",
        )

    return True, None
