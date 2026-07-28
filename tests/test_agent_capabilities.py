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
    assert llm.calls == 2
    assert calls == ["get_current_time"]
    assert "get_current_time" in llm.seen_tool_names[1]
    assert sum(
        message.get("role") == "user"
        and message.get("content") == "Проверь время"
        for message in llm.history
    ) == 1
