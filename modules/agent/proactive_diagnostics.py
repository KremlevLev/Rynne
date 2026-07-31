from __future__ import annotations

import asyncio
from dataclasses import replace
from collections.abc import Callable
from typing import Any

from modules.agent.proactive_vision import ProactiveVisionInsight
from modules.input_hub.models import RequestSource, UserRequest


class ProactiveDiagnosticRunner:
    """Enriches a visual hint with autonomous read-only evidence."""

    def __init__(
        self,
        agent: Any,
        *,
        workspace_provider: Callable[[], str | None] | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.agent = agent
        self.workspace_provider = workspace_provider
        self.timeout_seconds = max(5.0, timeout_seconds)

    async def investigate(
        self,
        insight: ProactiveVisionInsight,
    ) -> ProactiveVisionInsight:
        workspace_path = (
            self.workspace_provider()
            if self.workspace_provider is not None
            else None
        )
        allowed_tools = {
            "get_current_time",
            "get_system_status",
            "list_active_windows",
            "list_processes",
            "get_process_status",
            "read_process_output",
            "browser_status",
            "browser_get_page_text",
            "browser_screenshot",
        }
        if workspace_path:
            allowed_tools.update({
                "read_text_file",
                "get_file_diff",
                "search_files",
                "git_status",
                "git_diff",
                "git_log",
                "git_branch",
                "inspect_project",
            })
        metadata: dict[str, Any] = {
            "proactive_autonomous": True,
            "proactive_allowed_tools": sorted(allowed_tools),
            "active_window_title": insight.window_title,
        }
        if workspace_path:
            metadata["workspace_path"] = workspace_path

        request = UserRequest.from_text(
            (
                "Проведи фоновую read-only диагностику возможной проблемы. "
                "Используй доступные инструменты, чтобы собрать один-два "
                "проверяемых факта. Ничего не открывай, не меняй, не запускай, "
                "не вводи и не отправляй. Если безопасной проверки нет, "
                "заверши без действия.\n\n"
                f"Наблюдение: {insight.message}\n"
                f"Предложенный следующий шаг: {insight.suggested_request}"
            ),
            source=RequestSource.BACKGROUND_TASK,
            metadata=metadata,
        )
        try:
            response = await asyncio.wait_for(
                self.agent.run(request, use_tools=True),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return insight
        except Exception:
            return insight

        successful_count = int(
            response.data.get("successful_count") or 0
        )
        if not response.success or successful_count < 1:
            return insight

        evidence = " ".join(response.display_text.split())
        if not evidence:
            return insight
        evidence = evidence[:420]
        return replace(
            insight,
            message=(
                f"{insight.message}\n\n"
                f"Nova уже проверила под капотом: {evidence}"
            ),
            reason=(
                f"{insight.reason} Факты собраны только read-only "
                "инструментами; изменения не выполнялись."
            ),
        )
