from __future__ import annotations

import asyncio

from modules.agent.proactive_diagnostics import ProactiveDiagnosticRunner
from modules.agent.proactive_vision import ProactiveVisionInsight
from modules.domain.results import AssistantResponse


def make_insight() -> ProactiveVisionInsight:
    return ProactiveVisionInsight(
        should_interrupt=True,
        title="Ошибка сборки",
        message="В редакторе видна ошибка импорта.",
        reason="Строка подчёркнута диагностикой.",
        suggested_request="Проверь состояние проекта и предложи исправление.",
        action_label="Разобраться",
        confidence=0.94,
        window_title="main.py - VS Code",
        visual_fingerprint="abc123",
    )


class FakeDiagnosticAgent:
    def __init__(self, response: AssistantResponse) -> None:
        self.response = response
        self.requests = []

    async def run(self, request, **kwargs):
        self.requests.append((request, kwargs))
        return self.response


def test_proactive_diagnostic_enriches_with_read_only_evidence() -> None:
    agent = FakeDiagnosticAgent(AssistantResponse(
        display_text="Выполнено — состояние системы проверено.",
        speech_text="Проверено.",
        success=True,
        data={"successful_count": 1},
    ))
    runner = ProactiveDiagnosticRunner(
        agent,
        workspace_path="C:/workspace",
    )

    enriched = asyncio.run(runner.investigate(make_insight()))

    assert "уже проверила под капотом" in enriched.message
    request, kwargs = agent.requests[0]
    assert request.metadata["proactive_autonomous"] is True
    assert request.source.value == "background_task"
    assert kwargs["use_tools"] is True


def test_proactive_diagnostic_keeps_hint_when_no_tool_ran() -> None:
    insight = make_insight()
    agent = FakeDiagnosticAgent(AssistantResponse(
        display_text="Нужны уточнения.",
        speech_text="Нужны уточнения.",
        success=False,
        data={"successful_count": 0},
    ))
    runner = ProactiveDiagnosticRunner(
        agent,
        workspace_path="C:/workspace",
    )

    assert asyncio.run(runner.investigate(insight)) == insight
