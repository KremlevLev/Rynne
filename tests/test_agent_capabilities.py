from __future__ import annotations

import asyncio

from modules.application.agent import (
    AgentService,
    DYNAMIC_TOOL_DISCOVERY_NAME,
    is_contextual_follow_up,
)
from modules.agent.execution_memory import ExecutionMemory
from modules.agent.skill_library import SkillLibrary
from modules.brain.model_gateway import ModelResponse
from modules.domain.results import ToolResult
from modules.tools.runtime import ToolRegistry, ToolRunner
from modules.tools.base import RiskLevel


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


def test_contextual_follow_up_detection_is_conservative() -> None:
    assert is_contextual_follow_up("а теперь там мою активность?")
    assert is_contextual_follow_up("так открой его")
    assert is_contextual_follow_up("что на этой странице?")
    assert not is_contextual_follow_up("Запусти все приложения")
    assert not is_contextual_follow_up("Расскажи про квантовую физику")


class ContextualBrowserLLM:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.calls: list[dict] = []

    async def complete(self, **kwargs) -> ModelResponse:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            tool_names = {
                schema["function"]["name"]
                for schema in (kwargs.get("tools") or [])
            }
            assert "browser_open_url" in tool_names
            assert "CONTEXTUAL COMMAND CONTINUATION" in (
                kwargs["messages"][0]["content"]
            )
            return ModelResponse(
                provider="fake",
                model="fake",
                key_label="test",
                text="",
                tool_calls=[{
                    "id": "open_activity",
                    "type": "function",
                    "function": {
                        "name": "browser_open_url",
                        "arguments": (
                            '{"url":"https://openrouter.ai/activity"}'
                        ),
                    },
                }],
            )
        return ModelResponse(
            provider="fake",
            model="fake",
            key_label="test",
            text="Страница активности открыта.",
            tool_calls=[],
        )


def test_agent_continues_elliptical_browser_command_from_history() -> None:
    opened: list[str] = []
    schema = {
        "type": "function",
        "function": {
            "name": "browser_open_url",
            "description": "Открывает URL в браузере.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    }
    registry = ToolRegistry.from_legacy(
        [schema],
        {"browser_open_url": lambda url: (
            opened.append(url) or ToolResult.ok("Открыто.")
        )},
    )
    llm = ContextualBrowserLLM()
    agent = AgentService(llm, registry, ToolRunner(registry))
    agent.history.extend([
        {"role": "user", "content": "Включи браузер"},
        {"role": "assistant", "content": "Браузер открыт."},
    ])

    response = asyncio.run(
        agent.run("а теперь там открой мою активность")
    )

    assert response.success
    assert opened == ["https://openrouter.ai/activity"]


class DynamicToolDiscoveryLLM:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.calls: list[dict] = []

    async def complete(self, **kwargs) -> ModelResponse:
        self.calls.append(kwargs)
        tool_names = {
            schema["function"]["name"]
            for schema in (kwargs.get("tools") or [])
        }
        if len(self.calls) == 1:
            assert DYNAMIC_TOOL_DISCOVERY_NAME in tool_names
            assert "quantum_operation" not in tool_names
            return ModelResponse(
                provider="fake",
                model="fake",
                key_label="test",
                text="",
                tool_calls=[{
                    "id": "discover_quantum",
                    "type": "function",
                    "function": {
                        "name": DYNAMIC_TOOL_DISCOVERY_NAME,
                        "arguments": '{"query":"quantum flux capacitor"}',
                    },
                }],
            )
        if len(self.calls) == 2:
            assert "quantum_operation" in tool_names
            assert any(
                message.get("role") == "tool"
                and message.get("name") == DYNAMIC_TOOL_DISCOVERY_NAME
                and "quantum_operation" in message.get("content", "")
                for message in kwargs["messages"]
            )
            return ModelResponse(
                provider="fake",
                model="fake",
                key_label="test",
                text="",
                tool_calls=[{
                    "id": "run_quantum",
                    "type": "function",
                    "function": {
                        "name": "quantum_operation",
                        "arguments": "{}",
                    },
                }],
            )
        return ModelResponse(
            provider="fake",
            model="fake",
            key_label="test",
            text="Операция выполнена.",
            tool_calls=[],
        )


def test_agent_discovers_and_executes_deferred_tool() -> None:
    schemas = []
    handlers = {}
    for index in range(35):
        name = f"decoy_operation_{index:02d}"
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": "Выполняет служебную операцию.",
                "parameters": {"type": "object", "properties": {}},
            },
        })
        handlers[name] = lambda: ToolResult.ok("Служебная операция.")
    schemas.append({
        "type": "function",
        "function": {
            "name": "quantum_operation",
            "description": (
                "Выполняет служебную quantum flux capacitor операцию."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    })
    executed: list[str] = []
    handlers["quantum_operation"] = lambda: (
        executed.append("quantum_operation")
        or ToolResult.ok("Quantum операция выполнена.")
    )

    registry = ToolRegistry.from_legacy(schemas, handlers)
    llm = DynamicToolDiscoveryLLM()
    agent = AgentService(llm, registry, ToolRunner(registry))

    response = asyncio.run(agent.run("Выполни служебную операцию"))

    assert response.success
    assert executed == ["quantum_operation"]
    assert len(llm.calls) == 3
    assert "quantum_operation" in agent._sticky_tool_names


class SkillAwareLLM:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.calls = 0

    async def complete(self, **kwargs) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            assert "Skill: Light Control" in kwargs["messages"][0]["content"]
            assert "Проверь состояние лампы" in kwargs["messages"][0]["content"]
            return ModelResponse(
                provider="fake",
                model="fake",
                key_label="test",
                text="",
                tool_calls=[{
                    "id": "light_on",
                    "type": "function",
                    "function": {
                        "name": "control_light",
                        "arguments": "{}",
                    },
                }],
            )
        return ModelResponse(
            provider="fake",
            model="fake",
            key_label="test",
            text="Свет включён.",
            tool_calls=[],
        )


def test_agent_injects_workspace_skill_into_execution_loop(tmp_path) -> None:
    skill_dir = tmp_path / ".nova" / "skills" / "light"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: Light Control
triggers: [лампа, свет]
tools: [control_light]
---
Проверь состояние лампы, затем переключи её.
""",
        encoding="utf-8",
    )
    schema = {
        "type": "function",
        "function": {
            "name": "control_light",
            "description": "Управляет светом.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    executed: list[str] = []
    registry = ToolRegistry.from_legacy(
        [schema],
        {"control_light": lambda: (
            executed.append("control_light") or ToolResult.ok("Включено.")
        )},
    )
    llm = SkillAwareLLM()
    agent = AgentService(
        llm,
        registry,
        ToolRunner(registry),
        skill_library=SkillLibrary(
            tmp_path / "global",
            tmp_path / "no-builtins",
        ),
    )
    from modules.input_hub.models import UserRequest
    request = UserRequest.from_text(
        "Включи свет",
        metadata={"workspace_path": str(tmp_path)},
    )

    response = asyncio.run(agent.run(request))

    assert response.success
    assert executed == ["control_light"]


class TwoPromisesThenToolLLM(RefusalThenToolLLM):
    async def complete(self, **kwargs) -> ModelResponse:
        self.calls += 1
        schemas = kwargs.get("tools") or []
        self.seen_tool_names.append({
            schema["function"]["name"]
            for schema in schemas
        })
        if self.calls <= 2:
            return ModelResponse(
                provider="fake",
                model="fake",
                key_label="test",
                text="Хорошо, сейчас проверю.",
                tool_calls=[],
            )
        if self.calls == 3:
            assert "TOOL CALL REPAIR" in kwargs["messages"][0]["content"]
            return ModelResponse(
                provider="fake",
                model="fake",
                key_label="test",
                text="",
                tool_calls=[{
                    "id": "call_time_repaired",
                    "type": "function",
                    "function": {
                        "name": "get_current_time",
                        "arguments": "{}",
                    },
                }],
            )
        return ModelResponse(
            provider="fake",
            model="fake",
            key_label="test",
            text="Готово.",
            tool_calls=[],
        )


def test_action_promise_gets_second_tool_call_repair() -> None:
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
    registry = ToolRegistry.from_legacy(
        [schema],
        {"get_current_time": lambda: (
            calls.append("get_current_time")
            or ToolResult.ok("Время проверено.")
        )},
    )
    llm = TwoPromisesThenToolLLM()
    agent = AgentService(llm, registry, ToolRunner(registry))

    response = asyncio.run(agent.run("Посмотри текущее время"))

    assert response.success
    assert calls == ["get_current_time"]
    assert llm.calls == 4


class CaptureAmbientToolsLLM:
    def __init__(self) -> None:
        self.history = []
        self.tool_names: set[str] = set()

    async def complete(self, **kwargs) -> ModelResponse:
        self.tool_names = {
            schema["function"]["name"]
            for schema in (kwargs.get("tools") or [])
        }
        return ModelResponse(
            provider="fake",
            model="fake",
            key_label="test",
            text="Безопасная проверка не требуется.",
            tool_calls=[],
        )


def test_ambient_agent_never_receives_mutating_tool_schemas() -> None:
    schemas = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
        for name in ("get_system_status", "open_application")
    ]
    registry = ToolRegistry.from_legacy(
        schemas,
        {
            "get_system_status": lambda: ToolResult.ok("ok"),
            "open_application": lambda: ToolResult.ok("opened"),
        },
    )
    assert registry.get("get_system_status").risk == RiskLevel.READ_ONLY
    llm = CaptureAmbientToolsLLM()
    agent = AgentService(llm, registry, ToolRunner(registry))

    from modules.input_hub.models import RequestSource, UserRequest
    request = UserRequest.from_text(
        "Проверь систему и открой приложение",
        source=RequestSource.BACKGROUND_TASK,
        metadata={"proactive_autonomous": True},
    )
    asyncio.run(agent.run(request, use_tools=True))

    assert llm.tool_names == {"get_system_status"}


def test_ambient_agent_history_is_isolated_from_user_conversation() -> None:
    registry = ToolRegistry.from_legacy([], {})
    llm = CaptureAmbientToolsLLM()
    llm.history = [{"role": "user", "content": "Основной диалог"}]

    ambient = AgentService(
        llm,
        registry,
        ToolRunner(registry),
        isolated_history=True,
    )

    assert ambient.history == []
    assert llm.history == [
        {"role": "user", "content": "Основной диалог"}
    ]


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


def test_agent_continues_tool_loop_until_full_goal(tmp_path) -> None:
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
                "name": "browser_screenshot",
                "description": "Сохраняет снимок страницы.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "full_page": {"type": "boolean"},
                    },
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

    def browser_screenshot(full_page: bool = False) -> ToolResult:
        executed.append(f"screenshot:{full_page}")
        return ToolResult.ok("Скриншот сохранён: activity.png")

    registry = ToolRegistry.from_legacy(
        schemas,
        {
            "browser_open_url": browser_open_url,
            "browser_get_page_text": browser_get_page_text,
            "browser_screenshot": browser_screenshot,
        },
    )
    llm = SequentialBrowserLLM()
    agent = AgentService(
        llm,
        registry,
        ToolRunner(registry),
        execution_memory=ExecutionMemory(tmp_path / "patterns.json"),
    )

    response = asyncio.run(
        agent.run(
            "Открой OpenRouter, проверь мою активность и сделай скрин"
        )
    )

    assert response.success
    assert len(llm.calls) == 4
    assert executed == [
        "open:https://openrouter.ai/activity",
        "read",
        "screenshot:False",
    ]
    learned = (tmp_path / "patterns.json").read_text(encoding="utf-8")
    assert "browser_open_url" in learned
    assert "browser_screenshot" in learned
