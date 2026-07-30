from __future__ import annotations

import asyncio

from modules.application.agent import AgentService
from modules.brain.model_gateway import ModelResponse
from modules.domain.results import ToolResult
from modules.tools.runtime import ToolRegistry, ToolRunner


class RefusalThenToolLLM:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.calls = 0
        self.seen_tool_names: list[set[str]] = []

    async def complete(self, **kwargs) -> ModelResponse:
        self.calls += 1
        schemas = kwargs.get("tools") or []
        self.seen_tool_names.append({
            schema["function"]["name"]
            for schema in schemas
        })

        if self.calls == 1:
            return ModelResponse(
                provider="fake",
                model="fake",
                key_label="test",
                text="Я не могу это сделать.",
                tool_calls=[],
            )

        return ModelResponse(
            provider="fake",
            model="fake",
            key_label="test",
            text="",
            tool_calls=[
                {
                    "id": "call_time",
                    "type": "function",
                    "function": {
                        "name": "get_current_time",
                        "arguments": "{}",
                    },
                }
            ],
        )


def test_action_refusal_retries_with_real_tools() -> None:
    calls: list[str] = []
    schema = {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Возвращает текущее время.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }

    def get_current_time() -> ToolResult:
        calls.append("get_current_time")
        return ToolResult.ok("Время проверено.")

    registry = ToolRegistry.from_legacy(
        [schema],
        {"get_current_time": get_current_time},
    )
    llm = RefusalThenToolLLM()
    agent = AgentService(
        llm,
        registry,
        ToolRunner(registry),
    )

    response = asyncio.run(
        agent.run("Проверь время")
    )

    assert response.success
    # После recovery агент один раз предлагает модели проверить результат;
    # повторный идентичный tool call блокируется дедупликатором.
    assert llm.calls == 3
    assert calls == ["get_current_time"]
    assert "get_current_time" in llm.seen_tool_names[1]
    assert sum(
        message.get("role") == "user"
        and message.get("content") == "Проверь время"
        for message in llm.history
    ) == 1


class SequentialBrowserLLM:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.calls: list[dict] = []

    async def complete(self, **kwargs) -> ModelResponse:
        self.calls.append(kwargs)
        call_number = len(self.calls)

        if call_number == 1:
            return ModelResponse(
                provider="fake",
                model="fake",
                key_label="test",
                text="",
                tool_calls=[
                    {
                        "id": "call_open",
                        "type": "function",
                        "function": {
                            "name": "browser_open_url",
                            "arguments": (
                                '{"url":"https://openrouter.ai/activity"}'
                            ),
                        },
                    }
                ],
            )

        if call_number == 2:
            assert any(
                message.get("role") == "tool"
                and "OpenRouter открыт" in message.get("content", "")
                for message in kwargs["messages"]
            )
            return ModelResponse(
                provider="fake",
                model="fake",
                key_label="test",
                text="",
                tool_calls=[
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {
                            "name": "browser_get_page_text",
                            "arguments": "{}",
                        },
                    }
                ],
            )

        return ModelResponse(
            provider="fake",
            model="fake",
            key_label="test",
            text="Активность проверена.",
            tool_calls=[],
        )


def test_agent_continues_tool_loop_until_full_goal() -> None:
    executed: list[str] = []
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "browser_open_url",
                "description": "Открывает URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                        },
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_get_page_text",
                "description": "Читает текущую страницу.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
    ]

    def browser_open_url(
        url: str,
    ) -> ToolResult:
        executed.append(f"open:{url}")
        return ToolResult.ok("OpenRouter открыт.")

    def browser_get_page_text() -> ToolResult:
        executed.append("read")
        return ToolResult.ok("Активность: 42 запроса.")

    registry = ToolRegistry.from_legacy(
        schemas,
        {
            "browser_open_url": browser_open_url,
            "browser_get_page_text": browser_get_page_text,
        },
    )
    llm = SequentialBrowserLLM()
    agent = AgentService(
        llm,
        registry,
        ToolRunner(registry),
    )

    response = asyncio.run(
        agent.run(
            "Открой OpenRouter и проверь мою активность"
        )
    )

    assert response.success
    assert len(llm.calls) == 3
    assert executed == [
        "open:https://openrouter.ai/activity",
        "read",
    ]
