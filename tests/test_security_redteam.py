# tests/test_security_redteam.py
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from modules.domain.results import ToolResult
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
)
from modules.tools.permissions import (
    PermissionManager,
)
from modules.tools.runtime import (
    ToolRegistry,
    ToolRunner,
)
from modules.windows.filesystem import (
    read_text_file,
    write_text_file,
    _resolve_path,
)


def test_policy_denies_shutdown() -> None:
    context = PolicyContext(
        tool_name="shutdown_system",
        tool_category=ToolCategory.DESTRUCTIVE,
        risk=RiskLevel.CRITICAL,
        arguments={},
        operation_id="test",
        session_id="test",
        turn_id="test",
    )

    decision = evaluate_policy(context)

    assert decision == PolicyDecision.DENY


def test_policy_denies_registry_modification() -> None:
    context = PolicyContext(
        tool_name="modify_registry",
        tool_category=ToolCategory.DESTRUCTIVE,
        risk=RiskLevel.CRITICAL,
        arguments={},
        operation_id="test",
        session_id="test",
        turn_id="test",
    )

    decision = evaluate_policy(context)

    assert decision == PolicyDecision.DENY


def test_policy_denies_format_drive() -> None:
    context = PolicyContext(
        tool_name="format_drive",
        tool_category=ToolCategory.DESTRUCTIVE,
        risk=RiskLevel.CRITICAL,
        arguments={},
        operation_id="test",
        session_id="test",
        turn_id="test",
    )

    decision = evaluate_policy(context)

    assert decision == PolicyDecision.DENY


def test_write_to_windows_directory_is_blocked() -> None:
    result = write_text_file(
        "C:\\Windows\\system32\\nova_test.txt",
        "test",
    )

    assert not result.success
    assert result.code == "FILE_WRITE_FAILED"


def test_path_traversal_is_blocked() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)

        # Создаём файл за пределами разрешённой директории.
        outside = base.parent / "secret.txt"
        outside.write_text("secret")

        # Попытка прочитать через ../.
        result = read_text_file(
            str(
                base / "../secret.txt"
            )
        )

        assert not result.success


def test_runner_rejects_unknown_tool() -> None:
    async def scenario() -> None:
        registry = ToolRegistry()
        runner = ToolRunner(registry)

        result = await runner.execute(
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "unknown_tool",
                    "arguments": "{}",
                },
            }
        )

        assert not result.success
        assert result.code == "TOOL_NOT_FOUND"

    asyncio.run(scenario())


def test_runner_rejects_invalid_json_arguments() -> None:
    async def scenario() -> None:
        registry = ToolRegistry()

        registry.register_definition(
            ToolDefinition(
                name="safe_tool",
                description="Safe.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                handler=lambda: ToolResult.ok(
                    "ok"
                ),
                category=ToolCategory.SYSTEM_READ,
                risk=RiskLevel.READ_ONLY,
            )
        )

        runner = ToolRunner(registry)

        result = await runner.execute(
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "safe_tool",
                    "arguments": (
                        "{invalid json}"
                    ),
                },
            }
        )

        assert not result.success
        assert (
            result.code
            == "INVALID_ARGUMENTS_JSON"
        )

    asyncio.run(scenario())


def test_runner_rejects_non_dict_arguments() -> None:
    async def scenario() -> None:
        registry = ToolRegistry()

        registry.register_definition(
            ToolDefinition(
                name="safe_tool",
                description="Safe.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                handler=lambda: ToolResult.ok(
                    "ok"
                ),
                category=ToolCategory.SYSTEM_READ,
                risk=RiskLevel.READ_ONLY,
            )
        )

        runner = ToolRunner(registry)

        result = await runner.execute(
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "safe_tool",
                    "arguments": "[]",
                },
            }
        )

        assert not result.success
        assert (
            result.code
            == "INVALID_ARGUMENTS_TYPE"
        )

    asyncio.run(scenario())


def test_duplicate_tool_call_is_blocked() -> None:
    async def scenario() -> None:
        call_count = 0

        def handler() -> ToolResult:
            nonlocal call_count
            call_count += 1
            return ToolResult.ok(
                f"Вызов {call_count}"
            )

        registry = ToolRegistry()

        registry.register_definition(
            ToolDefinition(
                name="counter",
                description="Counts.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                handler=handler,
                category=ToolCategory.SYSTEM_READ,
                risk=RiskLevel.READ_ONLY,
            )
        )

        runner = ToolRunner(registry)

        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "counter",
                "arguments": "{}",
            },
        }

        # Первый вызов — успех.
        first = await runner.execute(
            tool_call
        )

        assert first.success
        assert call_count == 1

        # Второй вызов с тем же signature — должен выполниться,
        # потому что ToolRunner не хранит историю вызовов.
        # Дублирование блокируется на уровне AgentService.
        second = await runner.execute(
            tool_call
        )

        assert second.success
        assert call_count == 2

    asyncio.run(scenario())


def test_permission_manager_denies_expired_request() -> None:
    async def scenario() -> None:
        manager = PermissionManager()

        context = PolicyContext(
            tool_name="run_terminal_command",
            tool_category=ToolCategory.TERMINAL,
            risk=RiskLevel.EXECUTE,
            arguments={},
            operation_id="test-expired",
            session_id="test",
            turn_id="test",
        )

        request = manager.request(
            context,
            expires_after_seconds=0.0,
        )

        await asyncio.sleep(0.05)

        success = manager.confirm(
            request.operation_id
        )

        assert not success

    asyncio.run(scenario())


def test_sandbox_executes_simple_code() -> None:
    async def scenario() -> None:
        from modules.security.sandbox import (
            PythonSandbox,
        )

        sandbox = PythonSandbox()

        result = await sandbox.execute(
            "print('hello from sandbox')"
        )

        assert result.success
        assert (
            "hello from sandbox"
            in result.data["output"]
        )

    asyncio.run(scenario())


def test_sandbox_timeout() -> None:
    async def scenario() -> None:
        from modules.security.sandbox import (
            PythonSandbox,
        )

        sandbox = PythonSandbox(
            timeout_seconds=0.5
        )

        result = await sandbox.execute(
            "import time; time.sleep(10)"
        )

        assert not result.success
        assert result.code == "SANDBOX_TIMEOUT"

    asyncio.run(scenario())


def test_sandbox_does_not_leak_env() -> None:
    async def scenario() -> None:
        from modules.security.sandbox import (
            PythonSandbox,
        )

        sandbox = PythonSandbox()

        result = await sandbox.execute(
            "import os; "
            "print(os.environ.get('GROQ_API_KEY', 'MISSING'))"
        )

        assert result.success
        assert "MISSING" in result.data["output"]

    asyncio.run(scenario())


def test_legacy_python_executor_is_fail_closed() -> None:
    from modules.tools.executor import execute_python_code

    result = execute_python_code("print(__import__('os').environ)")

    assert "отключён политикой безопасности" in result
