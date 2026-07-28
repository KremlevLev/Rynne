# modules/tools/policy.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from modules.tools.base import (
    RiskLevel,
    ToolCategory,
    ToolContext,
    ToolDefinition,
)


logger = logging.getLogger("PolicyEngine")


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_STRONG_CONFIRMATION = (
        "require_strong_confirmation"
    )
    DENY = "deny"


@dataclass(slots=True)
class PolicyContext:
    tool_name: str
    tool_category: ToolCategory
    risk: RiskLevel
    arguments: dict[str, Any]

    operation_id: str
    session_id: str
    turn_id: str

    source: str = "assistant"
    expected_window: str | None = None
    working_directory: Path | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @classmethod
    def from_tool_context(
        cls,
        *,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> "PolicyContext":
        return cls(
            tool_name=definition.name,
            tool_category=definition.category,
            risk=definition.risk,
            arguments=arguments,
            operation_id=context.operation_id,
            session_id=context.session_id,
            turn_id=context.turn_id,
            source=context.source,
            expected_window=(
                context.expected_window
            ),
            working_directory=(
                context.working_directory
            ),
            metadata=context.metadata,
        )


# Инструменты, которые никогда не требуют подтверждения.
ALWAYS_ALLOWED = frozenset(
    {
        "get_current_time",
        "get_system_status",
        "list_active_windows",
        "get_active_reminders",
    }
)

# Инструменты, которые всегда требуют подтверждения.
ALWAYS_CONFIRMED = frozenset(
    {
        "execute_python_code",
        "run_terminal_command",
        "execute_cmd_command",
        "close_application",
        "manage_windows",
        "execute_plan",
        "undo_last_file_change",

    }
)

# Инструменты, которые запрещены по умолчанию.
ALWAYS_DENIED = frozenset(
    {
        "shutdown_system",
        "restart_system",
        "format_drive",
        "delete_system_file",
        "modify_registry",
    }
)


def evaluate_policy(
    policy_context: PolicyContext,
) -> PolicyDecision:
    if policy_context.tool_name in ALWAYS_DENIED:
        logger.warning(
            "Запрещённый инструмент %s.",
            policy_context.tool_name,
        )
        return PolicyDecision.DENY

    if policy_context.tool_name in ALWAYS_ALLOWED:
        return PolicyDecision.ALLOW

    if policy_context.tool_name in ALWAYS_CONFIRMED:
        return PolicyDecision.REQUIRE_CONFIRMATION

    if policy_context.risk == RiskLevel.READ_ONLY:
        return PolicyDecision.ALLOW

    if policy_context.risk == RiskLevel.LOW:
        return PolicyDecision.ALLOW

    if policy_context.risk == RiskLevel.WRITE:
        return PolicyDecision.ALLOW_WITH_WARNING

    if policy_context.risk == RiskLevel.EXECUTE:
        return PolicyDecision.REQUIRE_CONFIRMATION

    if policy_context.risk == RiskLevel.DESTRUCTIVE:
        return PolicyDecision.REQUIRE_STRONG_CONFIRMATION

    if policy_context.risk == RiskLevel.CRITICAL:
        return PolicyDecision.DENY

    return PolicyDecision.ALLOW


def format_confirmation_message(
    policy_context: PolicyContext,
) -> str:
    lines: list[str] = []

    lines.append(
        f"Действие: {policy_context.tool_name}"
    )

    if policy_context.arguments:
        lines.append(
            "Параметры: "
            + ", ".join(
                f"{key}={value}"
                for key, value in (
                    policy_context.arguments.items()
                )
            )
        )

    lines.append(
        f"Риск: {policy_context.risk.value}"
    )
    lines.append(
        f"Категория: "
        f"{policy_context.tool_category.value}"
    )

    if policy_context.expected_window:
        lines.append(
            f"Ожидаемое окно: "
            f"{policy_context.expected_window}"
        )

    if policy_context.working_directory:
        lines.append(
            f"Рабочий каталог: "
            f"{policy_context.working_directory}"
        )

    return "\n".join(lines)
