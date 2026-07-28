from __future__ import annotations

import asyncio
import json
from pathlib import Path

from modules.application.agent import (
    build_request_model_content,
)
from modules.domain.results import ToolResult
from modules.domain.workspace_context import (
    WorkspaceContextResolver,
)
from modules.input_hub.models import UserRequest
from modules.tools.base import (
    RiskLevel,
    ToolCategory,
    ToolContext,
    ToolDefinition,
)
from modules.tools.runtime import ToolRegistry, ToolRunner
from modules.tools.os_utils import run_terminal_command


class FakeProcess:
    def __init__(
        self,
        *,
        name: str,
        cwd: Path,
        children: list["FakeProcess"] | None = None,
    ) -> None:
        self._name = name
        self._cwd = cwd
        self._children = children or []

    def name(self) -> str:
        return self._name

    def cwd(self) -> str:
        return str(self._cwd)

    def children(self, *, recursive: bool) -> list["FakeProcess"]:
        assert recursive is True
        return self._children


def test_resolver_finds_project_in_terminal_child(
    tmp_path: Path,
) -> None:
    project = tmp_path / "nova-project"
    project.mkdir()
    (project / ".git").mkdir()
    terminal = FakeProcess(
        name="WindowsTerminal.exe",
        cwd=tmp_path,
        children=[
            FakeProcess(
                name="pwsh.exe",
                cwd=project,
            )
        ],
    )
    resolver = WorkspaceContextResolver(
        foreground_provider=lambda: (
            42,
            "PowerShell",
        ),
        process_provider=lambda pid: terminal,
    )

    snapshot = resolver.observe_foreground()

    assert snapshot is not None
    assert snapshot.path == project.resolve()
    assert snapshot.project_name == "nova-project"
    assert snapshot.process_name == "pwsh.exe"


def test_resolver_uses_recent_workspace_when_nova_has_focus(
    tmp_path: Path,
) -> None:
    project = tmp_path / "active-project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname='active-project'\n",
        encoding="utf-8",
    )
    active = {
        "process": FakeProcess(
            name="Code.exe",
            cwd=project,
        ),
        "title": "active-project - Visual Studio Code",
    }
    resolver = WorkspaceContextResolver(
        foreground_provider=lambda: (
            7,
            active["title"],
        ),
        process_provider=lambda pid: active["process"],
    )
    assert resolver.observe_foreground() is not None

    active["process"] = FakeProcess(
        name="python.exe",
        cwd=tmp_path,
    )
    active["title"] = "Nova"
    request = UserRequest.from_text(
        "Запусти тесты здесь"
    )

    snapshot = resolver.enrich(request)

    assert snapshot is not None
    assert snapshot.source == "recent_workspace"
    assert request.metadata["workspace_path"] == str(
        project.resolve()
    )


def test_workspace_is_added_to_model_content(
    tmp_path: Path,
) -> None:
    request = UserRequest.from_text(
        "Покажи git diff",
        metadata={
            "workspace_path": str(tmp_path),
            "workspace_name": "demo",
        },
    )

    content = build_request_model_content(request)

    assert isinstance(content, list)
    context = "\n".join(
        str(item.get("text") or "")
        for item in content
    )
    assert "Активный workspace: demo" in context
    assert str(tmp_path) in context


def test_runner_injects_workspace_into_supported_tool(
    tmp_path: Path,
) -> None:
    received: dict[str, str] = {}

    def handler(
        command: str,
        working_directory: str | None = None,
    ) -> ToolResult:
        received["command"] = command
        received["working_directory"] = str(
            working_directory
        )
        return ToolResult.ok("done")

    registry = ToolRegistry()
    registry.register_definition(
        ToolDefinition(
            name="workspace_terminal",
            description="Run in workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "working_directory": {
                        "type": "string",
                    },
                },
                "required": ["command"],
            },
            handler=handler,
            category=ToolCategory.SYSTEM_READ,
            risk=RiskLevel.READ_ONLY,
        )
    )
    runner = ToolRunner(registry)
    context = ToolContext.create(
        working_directory=tmp_path,
    )

    result = asyncio.run(
        runner.execute(
            {
                "id": "call_workspace",
                "type": "function",
                "function": {
                    "name": "workspace_terminal",
                    "arguments": json.dumps(
                        {"command": "pytest"}
                    ),
                },
            },
            context=context,
        )
    )

    assert result.success
    assert received == {
        "command": "pytest",
        "working_directory": str(
            tmp_path.resolve()
        ),
    }


def test_terminal_process_runs_inside_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import subprocess
    from modules.tools import executor

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=b"ok",
            stderr=b"",
        )

    monkeypatch.setattr(
        executor,
        "prompt_hitl_permission",
        lambda title, details: True,
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        fake_run,
    )

    result = run_terminal_command(
        "python -m pytest -q",
        working_directory=str(tmp_path),
    )

    assert captured["cwd"] == str(tmp_path.resolve())
    assert captured["command"] == "python -m pytest -q"
    assert "ok" in result
