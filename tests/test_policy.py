# tests/test_policy.py
from __future__ import annotations

from modules.tools.base import (
    RiskLevel,
    ToolCategory,
    ToolContext,
    ToolDefinition,
)
from modules.tools.policy import (
    PolicyContext,
    PolicyDecision,
    evaluate_policy,
    format_confirmation_message,
)


def create_policy_context(
    tool_name: str,
    risk: RiskLevel = RiskLevel.LOW,
    category: ToolCategory = ToolCategory.UNKNOWN,
) -> PolicyContext:
    context = ToolContext.create()

    definition = ToolDefinition(
        name=tool_name,
        description="Test tool.",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=lambda: "ok",
        risk=risk,
        category=category,
    )

    return PolicyContext.from_tool_context(
        definition=definition,
        arguments={},
        context=context,
    )


def test_read_only_is_allowed() -> None:
    context = create_policy_context(
        "get_current_time",
        risk=RiskLevel.READ_ONLY,
    )

    decision = evaluate_policy(context)

    assert decision == PolicyDecision.ALLOW


def test_low_risk_is_allowed() -> None:
    context = create_policy_context(
        "focus_window",
        risk=RiskLevel.LOW,
    )

    decision = evaluate_policy(context)

    assert decision == PolicyDecision.ALLOW


def test_write_risk_has_warning() -> None:
    context = create_policy_context(
        "type_text",
        risk=RiskLevel.WRITE,
    )

    decision = evaluate_policy(context)

    assert (
        decision
        == PolicyDecision.ALLOW_WITH_WARNING
    )


def test_execute_risk_requires_confirmation() -> None:
    context = create_policy_context(
        "run_terminal_command",
        risk=RiskLevel.EXECUTE,
    )

    decision = evaluate_policy(context)

    assert (
        decision
        == PolicyDecision.REQUIRE_CONFIRMATION
    )


def test_destructive_risk_requires_strong_confirmation() -> None:
    context = create_policy_context(
        "some_destructive_tool",
        risk=RiskLevel.DESTRUCTIVE,
    )

    decision = evaluate_policy(context)

    assert (
        decision
        == PolicyDecision.REQUIRE_STRONG_CONFIRMATION
    )


def test_critical_risk_is_denied() -> None:
    context = create_policy_context(
        "shutdown_system",
        risk=RiskLevel.CRITICAL,
    )

    decision = evaluate_policy(context)

    assert decision == PolicyDecision.DENY


def test_always_allowed_tools_are_allowed() -> None:
    for tool_name in (
        "get_current_time",
        "get_system_status",
        "list_active_windows",
        "get_active_reminders",
    ):
        context = create_policy_context(
            tool_name,
            risk=RiskLevel.READ_ONLY,
        )

        decision = evaluate_policy(context)

        assert decision == PolicyDecision.ALLOW


def test_always_confirmed_tools_require_confirmation() -> None:
    for tool_name in (
        "execute_python_code",
        "run_terminal_command",
        "execute_cmd_command",
        "close_application",
        "manage_windows",
        "undo_last_file_change",
    ):
        context = create_policy_context(
            tool_name,
            risk=RiskLevel.EXECUTE,
        )

        decision = evaluate_policy(context)

        assert (
            decision
            == PolicyDecision.REQUIRE_CONFIRMATION
        )


def test_always_denied_tools_are_denied() -> None:
    for tool_name in (
        "shutdown_system",
        "restart_system",
        "format_drive",
        "delete_system_file",
        "modify_registry",
    ):
        context = create_policy_context(
            tool_name,
            risk=RiskLevel.CRITICAL,
        )

        decision = evaluate_policy(context)

        assert decision == PolicyDecision.DENY


def test_confirmation_message_contains_tool_name() -> None:
    context = create_policy_context(
        "test_tool",
        risk=RiskLevel.EXECUTE,
    )

    message = format_confirmation_message(
        context
    )

    assert "test_tool" in message
    assert "риск" in message.lower()
