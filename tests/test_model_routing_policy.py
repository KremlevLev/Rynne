from __future__ import annotations

from modules.brain import model_router
from modules.brain.model_router import (
    TaskComplexity,
    build_model_route,
)


def test_groq_uses_only_text_and_vision_models(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_router,
        "GROQ_API_KEYS",
        ("groq-key",),
    )
    monkeypatch.setattr(
        model_router,
        "OPENROUTER_API_KEYS",
        (),
    )
    monkeypatch.setattr(
        model_router,
        "GEMINI_API_KEYS",
        (),
    )

    for complexity in (
        TaskComplexity.CHAT,
        TaskComplexity.BASIC_TOOL,
        TaskComplexity.COMPLEX_TOOL,
        TaskComplexity.ULTRA,
    ):
        route = build_model_route(complexity)
        assert [item.model for item in route] == [
            "openai/gpt-oss-120b"
        ]
        assert all(not item.supports_vision for item in route)

    vision_route = build_model_route(TaskComplexity.VISION)
    assert [item.model for item in vision_route] == [
        "qwen/qwen3.6-27b"
    ]
    assert vision_route[0].supports_vision is True
