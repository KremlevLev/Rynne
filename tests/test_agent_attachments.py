from __future__ import annotations

import asyncio

from modules.application.agent import AgentService
from modules.brain.model_gateway import ModelResponse
from modules.input_hub.models import (
    Attachment,
    AttachmentType,
    UserRequest,
)
from modules.tools.runtime import ToolRegistry, ToolRunner


class CapturingVisionLLM:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.calls: list[dict] = []

    async def complete(self, **kwargs) -> ModelResponse:
        self.calls.append(kwargs)
        return ModelResponse(
            provider="fake",
            model="vision",
            key_label="test",
            text="На изображении видна ошибка.",
            tool_calls=[],
        )


def test_user_request_image_is_sent_to_vision_model(
    tmp_path,
) -> None:
    image_path = tmp_path / "error.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    request = UserRequest.from_text(
        "Что за ошибка на изображении?",
        attachments=[
            Attachment(
                attachment_type=AttachmentType.IMAGE,
                path=str(image_path),
                mime_type="image/png",
            )
        ],
    )
    registry = ToolRegistry()
    llm = CapturingVisionLLM()
    agent = AgentService(
        llm,
        registry,
        ToolRunner(registry),
    )

    response = asyncio.run(agent.run(request))

    assert response.success
    assert len(llm.calls) == 1
    user_message = next(
        message
        for message in llm.calls[0]["messages"]
        if message.get("role") == "user"
    )
    content = user_message["content"]
    assert isinstance(content, list)
    image_item = next(
        item
        for item in content
        if item.get("type") == "image_url"
    )
    assert image_item["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert "base64," not in str(llm.history)
    assert "[ИЗОБРАЖЕНИЕ]" in str(llm.history)
