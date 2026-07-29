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

    direct_executor = DirectRequestExecutor(
        runner=ToolRunner(registry),
        preferences=PreferencesManager(),
    )

    agent = FakeAgent()

    dispatcher = RequestDispatcher(
        agent=agent,
        direct_executor=direct_executor,
    )

    return dispatcher, agent


def test_direct_request_does_not_call_agent() -> None:
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
        assert response.data[
            "model_calls"
        ] == 0
        assert agent.calls == []

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
