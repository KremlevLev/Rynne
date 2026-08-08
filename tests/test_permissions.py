# tests/test_permissions.py
from __future__ import annotations

import asyncio

from modules.tools.base import (
    RiskLevel,
    ToolCategory,
    ToolContext,
    ToolDefinition,
)
from modules.tools.policy import (
    PolicyContext,
    PolicyDecision,
)
from modules.tools.permissions import (
    PermissionManager,
)


def create_policy_context(
    tool_name: str,
    risk: RiskLevel = RiskLevel.LOW,
) -> PolicyContext:
    context = ToolContext.create()

    definition = ToolDefinition(
        name=tool_name,
        description="Test.",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=lambda: "ok",
        risk=risk,
        category=ToolCategory.UNKNOWN,
    )

    return PolicyContext.from_tool_context(
        definition=definition,
        arguments={},
        context=context,
    )


def test_low_risk_is_allowed_without_confirmation() -> None:
    manager = PermissionManager()

    context = create_policy_context(
        "focus_window",
        risk=RiskLevel.LOW,
    )

    allowed, reason = manager.check(context)

    assert allowed
    assert reason is None


def test_execute_risk_requires_confirmation() -> None:
    manager = PermissionManager()

    context = create_policy_context(
        "run_terminal_command",
        risk=RiskLevel.EXECUTE,
    )

    allowed, reason = manager.check(context)

    assert not allowed
    assert reason is None


def test_denied_tool_is_rejected() -> None:
    manager = PermissionManager()

    context = create_policy_context(
        "shutdown_system",
        risk=RiskLevel.CRITICAL,
    )

    allowed, reason = manager.check(context)

    assert not allowed
    assert reason is not None
    assert "запрещен" in reason.lower()


def test_confirm_and_deny_work() -> None:
    manager = PermissionManager()

    context = create_policy_context(
        "execute_python_code",
        risk=RiskLevel.EXECUTE,
    )

    request = manager.request(context)

    assert not request.resolved

    assert manager.confirm(
        request.operation_id
    )

    assert not manager.confirm(
        request.operation_id
    )


def test_deny_rejects_operation() -> None:
    manager = PermissionManager()

    context = create_policy_context(
        "execute_python_code",
        risk=RiskLevel.EXECUTE,
    )

    request = manager.request(context)

    assert manager.deny(
        request.operation_id
    )

    assert not manager.deny(
        request.operation_id
    )


def test_wait_for_confirmation_returns_true_for_low_risk() -> None:
    async def scenario() -> None:
        manager = PermissionManager()

        context = create_policy_context(
            "focus_window",
            risk=RiskLevel.LOW,
        )

        granted = (
            await manager.wait_for_confirmation(
                context
            )
        )

        assert granted

    asyncio.run(scenario())
def test_pending_requests_are_visible() -> None:
    manager = PermissionManager()

    context = create_policy_context(
        "run_terminal_command",
        risk=RiskLevel.EXECUTE,
    )

    request = manager.request(context)

    pending = manager.pending_requests()

    assert len(pending) == 1
    assert (
        pending[0]["operation_id"]
        == request.operation_id
    )


def test_confirmation_request_is_emitted_immediately() -> None:
    events: list[tuple[str, dict]] = []
    manager = PermissionManager(
        event_sink=lambda event_type, payload: events.append((event_type, payload))
    )
    context = create_policy_context(
        "run_terminal_command",
        risk=RiskLevel.EXECUTE,
    )

    manager.request(context)

    assert events[0][0] == "approval_requested"
    assert events[0][1]["operation_id"] == context.operation_id
    assert events[0][1]["tool_name"] == "run_terminal_command"


def test_wait_for_confirmation_can_be_confirmed() -> None:
    async def scenario() -> None:
        manager = PermissionManager()

        context = create_policy_context(
            "run_terminal_command",
            risk=RiskLevel.EXECUTE,
        )

        wait_task = asyncio.create_task(
            manager.wait_for_confirmation(
                context,
                timeout_seconds=2.0,
            )
        )

        await asyncio.sleep(0.05)

        pending = manager.pending_requests()

        assert len(pending) == 1

        operation_id = pending[0][
            "operation_id"
        ]

        assert manager.confirm(
            operation_id
        )

        granted = await wait_task

        assert granted

    asyncio.run(scenario())


def test_permission_timeout_denies() -> None:
    async def scenario() -> None:
        manager = PermissionManager()

        context = create_policy_context(
            "run_terminal_command",
            risk=RiskLevel.EXECUTE,
        )

        granted = (
            await manager.wait_for_confirmation(
                context,
                timeout_seconds=0.02,
            )
        )

        assert not granted

    asyncio.run(scenario())
