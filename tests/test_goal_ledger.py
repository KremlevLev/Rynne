from __future__ import annotations

import asyncio

from modules.agent.goal_ledger import GoalLedger


def test_authenticated_signup_cannot_finish_after_opening_browser_only() -> None:
    ledger = GoalLedger.from_request(
        "Открой notion.so, зарегистрируйся через Google, создай workspace Rynne Test",
        {"open_url_in_browser", "inspect_active_window", "click_ui_element", "type_text"},
    )
    missing = ledger.unmet([
        {"name": "open_url_in_browser", "result": {"success": True}},
    ])
    assert {item.key for item in missing} == {
        "browser_ui_inspection", "browser_ui_interaction", "browser_form_input"
    }
from modules.application.agent import AgentService
from modules.brain.model_gateway import ModelResponse
from modules.domain.results import ToolResult
from modules.tools.runtime import ToolRegistry, ToolRunner


def test_browser_goal_tracks_navigation_inspection_and_screenshot() -> None:
    ledger = GoalLedger.from_request(
        "Открой OpenRouter, проверь активность и сделай скриншот",
        {"browser_open_url", "browser_get_page_text", "browser_screenshot"},
    )

    assert {item.key for item in ledger.requirements} == {
        "browser_navigation", "browser_inspection", "screenshot",
    }


def test_code_change_requires_mutation_and_verification() -> None:
    ledger = GoalLedger.from_request(
        "Исправь ошибку в проекте",
        {"apply_text_patch", "run_project_tests", "read_text_file"},
    )

    assert {item.key for item in ledger.requirements} == {
        "workspace_change", "workspace_verification",
    }
    assert ledger.tool_hints == {"apply_text_patch", "run_project_tests"}


def test_telegram_message_requires_real_send_not_application_typing() -> None:
    ledger = GoalLedger.from_request(
        "Напиши Владу в Telegram: привет",
        {
            "mcp_telegram_business_resolve_chat",
            "mcp_telegram_business_send_message",
            "write_in_application",
        },
    )

    assert [item.key for item in ledger.requirements] == ["telegram_send"]
    assert ledger.tool_hints == {"mcp_telegram_business_send_message"}
    assert "подтвержден" not in ledger.requirements[0].description.lower()


def test_ledger_counts_only_successful_tool_results() -> None:
    ledger = GoalLedger.from_request(
        "Открой сайт и проверь страницу",
        {"browser_open_url", "browser_get_page_text"},
    )
    results = [
        {"name": "browser_open_url", "result": {"success": True}},
        {"name": "browser_get_page_text", "result": {"success": False}},
    ]

    assert [item.key for item in ledger.unmet(results)] == [
        "browser_inspection",
    ]


class PrematureCompletionLLM:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.calls: list[dict] = []

    async def complete(self, **kwargs) -> ModelResponse:
        self.calls.append(kwargs)
        call_number = len(self.calls)
        if call_number == 1:
            assert "GOAL COMPLETION LEDGER" in kwargs["messages"][0]["content"]
            return ModelResponse(
                provider="fake", model="fake", key_label="test", text="",
                tool_calls=[{
                    "id": "open", "type": "function",
                    "function": {
                        "name": "browser_open_url",
                        "arguments": '{"url":"https://openrouter.ai/activity"}',
                    },
                }],
            )
        if call_number == 2:
            return ModelResponse(
                provider="fake", model="fake", key_label="test",
                text="Готово, страница открыта.", tool_calls=[],
            )
        if call_number == 3:
            assert "COMPLETION GATE" in kwargs["messages"][0]["content"]
            assert "фактическое содержимое" in kwargs["messages"][0]["content"]
            return ModelResponse(
                provider="fake", model="fake", key_label="test", text="",
                tool_calls=[{
                    "id": "inspect", "type": "function",
                    "function": {
                        "name": "browser_get_page_text", "arguments": "{}",
                    },
                }],
            )
        return ModelResponse(
            provider="fake", model="fake", key_label="test",
            text="Активность проверена.", tool_calls=[],
        )


def test_completion_gate_replans_after_premature_success() -> None:
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "browser_open_url",
                "description": "Открывает URL.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_get_page_text",
                "description": "Читает страницу.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    executed: list[str] = []
    registry = ToolRegistry.from_legacy(
        schemas,
        {
            "browser_open_url": lambda url: (
                executed.append("browser_open_url") or ToolResult.ok("Открыто")
            ),
            "browser_get_page_text": lambda: (
                executed.append("browser_get_page_text")
                or ToolResult.ok("Activity: 42 requests")
            ),
        },
    )
    llm = PrematureCompletionLLM()
    agent = AgentService(llm, registry, ToolRunner(registry))

    response = asyncio.run(
        agent.run("Открой OpenRouter и проверь мою активность")
    )

    assert response.success
    assert executed == ["browser_open_url", "browser_get_page_text"]
    assert len(llm.calls) == 4


class StubbornCompletionLLM:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.calls = 0

    async def complete(self, **kwargs) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                provider="fake", model="fake", key_label="test", text="",
                tool_calls=[{
                    "id": "open_only", "type": "function",
                    "function": {
                        "name": "browser_open_url",
                        "arguments": '{"url":"https://openrouter.ai/activity"}',
                    },
                }],
            )
        return ModelResponse(
            provider="fake", model="fake", key_label="test",
            text="Всё готово.", tool_calls=[],
        )


def test_incomplete_ledger_never_reports_success() -> None:
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "browser_open_url",
                "description": "Открывает URL.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_get_page_text",
                "description": "Читает страницу.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    registry = ToolRegistry.from_legacy(
        schemas,
        {
            "browser_open_url": lambda url: ToolResult.ok("Открыто"),
            "browser_get_page_text": lambda: ToolResult.ok("Прочитано"),
        },
    )
    agent = AgentService(
        StubbornCompletionLLM(), registry, ToolRunner(registry)
    )

    response = asyncio.run(
        agent.run("Открой OpenRouter и проверь мою активность")
    )

    assert not response.success
    assert response.error_code == "GOAL_INCOMPLETE"
    assert response.data["goal_ledger"]["missing"] == ["browser_inspection"]
    assert "Задача пока не завершена" in response.display_text
