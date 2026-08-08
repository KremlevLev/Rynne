# tests/test_request_dispatcher.py
from __future__ import annotations

import asyncio

from modules.application.preferences import (
    PreferencesManager,
)
from modules.application.request_dispatcher import (
    RequestDispatcher,
)
from modules.domain.results import (
    AssistantResponse,
    ToolResult,
)
from modules.input_hub.models import (
    Attachment,
    AttachmentType,
    UserRequest,
)
from modules.routing.direct_executor import (
    DirectRequestExecutor,
)
from modules.tools.base import (
    RiskLevel,
    ToolCategory,
    ToolDefinition,
)
from modules.tools.runtime import (
    ToolRegistry,
    ToolRunner,
)


class FakeAgent:
    def __init__(self) -> None:
        self.calls = []
        self.external_turns = []
        self.contextual_follow_ups = False

    def can_resolve_contextual_follow_up(self, text):
        return self.contextual_follow_ups

    def record_external_turn(
        self,
        user_text,
        assistant_text,
    ):
        self.external_turns.append(
            (user_text, assistant_text)
        )

    async def run(
        self,
        request,
        use_tools=True,
        has_image=False,
    ):
        self.calls.append(
            {
                "request": request,
                "use_tools": use_tools,
                "has_image": has_image,
            }
        )

        return AssistantResponse(
            display_text="Ответ модели.",
            speech_text="Ответ модели.",
        )


def create_dispatcher():
    registry = ToolRegistry()

    registry.register_definition(
        ToolDefinition(
            name="get_current_time",
            description="Время.",
            parameters={
                "type": "object",
                "properties": {},
            },
            handler=lambda: ToolResult.ok(
                "Сейчас 12:00."
            ),
            category=(
                ToolCategory.SYSTEM_READ
            ),
            risk=RiskLevel.READ_ONLY,
        )
    )
    opened_urls = []
    opened_chats = []
    registry.register_definition(
        ToolDefinition(
            name="open_url_in_browser",
            description="Open URL in browser.",
            parameters={
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["app_name", "url"],
            },
            handler=lambda app_name, url: (
                opened_urls.append((app_name, url))
                or ToolResult.ok("Telegram открыт.")
            ),
            category=ToolCategory.WEB_READ,
            risk=RiskLevel.LOW,
        )
    )
    registry.register_definition(
        ToolDefinition(
            name="open_telegram_chat",
            description="Open Telegram chat.",
            parameters={
                "type": "object",
                "properties": {
                    "contact": {"type": "string"},
                },
                "required": ["contact"],
            },
            handler=lambda contact: (
                opened_chats.append(contact)
                or ToolResult.ok("Telegram chat selected.")
            ),
            category=ToolCategory.GUI_WRITE,
            risk=RiskLevel.LOW,
        )
    )

    direct_executor = DirectRequestExecutor(
        runner=ToolRunner(registry),
        preferences=PreferencesManager(),
    )

    agent = FakeAgent()

    dispatcher = RequestDispatcher(
        agent=agent,
        direct_executor=direct_executor,
    )

    agent.opened_urls = opened_urls
    agent.opened_chats = opened_chats
    return dispatcher, agent


def test_tool_backed_direct_request_always_calls_agent() -> None:
    async def scenario() -> None:
        dispatcher, agent = (
            create_dispatcher()
        )

        response = await dispatcher.dispatch(
            UserRequest.from_text(
                "Который час?"
            )
        )

        assert response.success
        assert len(agent.calls) == 1
        assert agent.calls[0]["use_tools"] is True
        assert agent.external_turns == []

    asyncio.run(scenario())


def test_image_context_never_uses_direct_bypass(
    tmp_path,
) -> None:
    async def scenario() -> None:
        dispatcher, agent = create_dispatcher()
        image = tmp_path / "context.png"
        image.write_bytes(b"image")

        response = await dispatcher.dispatch(
            UserRequest.from_text(
                "Который час?",
                attachments=[
                    Attachment(
                        attachment_type=(
                            AttachmentType.SCREENSHOT
                        ),
                        path=str(image),
                    )
                ],
            )
        )

        assert response.success
        assert len(agent.calls) == 1
        assert agent.calls[0]["has_image"] is True

    asyncio.run(scenario())


def test_known_service_in_named_browser_bypasses_model_safely() -> None:
    async def scenario() -> None:
        dispatcher, agent = create_dispatcher()

        response = await dispatcher.dispatch(
            UserRequest.from_text("Открой гугл хром, а в нем телеграм")
        )

        assert response.success
        assert agent.calls == []
        assert agent.opened_urls == [
            ("google chrome", "https://web.telegram.org/a/")
        ]
        assert response.data["model_calls"] == 0

    asyncio.run(scenario())


def test_telegram_chat_bypasses_model_safely() -> None:
    async def scenario() -> None:
        dispatcher, agent = create_dispatcher()

        response = await dispatcher.dispatch(
            UserRequest.from_text("Попробуй открыть чат с Владиславом")
        )

        assert response.success
        assert agent.calls == []
        assert agent.opened_chats == ["владиславом"]
        assert response.data["model_calls"] == 0

    asyncio.run(scenario())


def test_chat_request_calls_agent() -> None:
    async def scenario() -> None:
        dispatcher, agent = (
            create_dispatcher()
        )

        response = await dispatcher.dispatch(
            UserRequest.from_text(
                "Привет"
            )
        )

        assert response.success
        assert len(agent.calls) == 1

    asyncio.run(scenario())


def test_clarification_does_not_call_agent() -> None:
    async def scenario() -> None:
        dispatcher, agent = (
            create_dispatcher()
        )

        response = await dispatcher.dispatch(
            UserRequest.from_text(
                "Запусти все приложения, которые можешь"
            )
        )

        assert not response.success
        assert (
            response.error_code
            == "CLARIFICATION_REQUIRED"
        )
        assert agent.calls == []

    asyncio.run(scenario())


def test_contextual_follow_up_bypasses_local_clarification() -> None:
    async def scenario() -> None:
        dispatcher, agent = create_dispatcher()
        agent.contextual_follow_ups = True

        response = await dispatcher.dispatch(
            UserRequest.from_text(
                "так запусти все приложения"
            )
        )

        assert response.success
        assert len(agent.calls) == 1
        assert agent.calls[0]["use_tools"] is True
        assert agent.external_turns == []

    asyncio.run(scenario())
