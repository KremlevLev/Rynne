# modules/brain/llm.py
from __future__ import annotations

import logging
import os
from typing import Any

from modules.brain.model_gateway import (
    ModelGateway,
    ModelResponse,
)
from modules.brain.model_router import (
    ModelCandidate,
)
from modules.brain.tool_calls import (
    extract_xml_tool_calls,
)
from modules.local.inference import (
    LocalLLMFallback,
    messages_to_local_prompt,
)


logger = logging.getLogger("RynneLLM")


class NovaLLM:
    def __init__(
        self,
        model: str | None = None,
    ) -> None:
        self.primary_model = model
        self.history: list[dict[str, Any]] = []

        self.gateway = ModelGateway()
        self.local_fallback = LocalLLMFallback()

        self.enable_local_fallback = (
            os.getenv(
                "NOVA_ENABLE_LOCAL_LLM_FALLBACK",
                "true",
            ).lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        )

    async def complete(
        self,
        *,
        candidates: list[ModelCandidate],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        allow_tools: bool = True,
        requires_vision: bool = False,
    ) -> ModelResponse:
        try:
            return await self.gateway.complete(
                candidates=candidates,
                messages=messages,
                tools=tools,
                allow_tools=allow_tools,
                requires_vision=requires_vision,
            )

        except Exception as cloud_error:
            # Локальная модель не используется для:
            # - tool calling;
            # - vision;
            # - запросов, где переданы инструменты.
            local_allowed = (
                self.enable_local_fallback
                and self.local_fallback.available
                and not requires_vision
                and not allow_tools
                and not tools
            )

            if not local_allowed:
                raise

            logger.warning(
                (
                    "Облачные модели недоступны. "
                    "Пробую локальный LLM fallback: %s"
                ),
                cloud_error,
            )

            prompt = messages_to_local_prompt(
                messages
            )

            local_result = (
                await self.local_fallback.generate(
                    prompt
                )
            )

            if not local_result.success:
                raise RuntimeError(
                    (
                        "Облачные модели недоступны, "
                        "локальный fallback также завершился "
                        f"ошибкой: {local_result.error}"
                    )
                ) from cloud_error

            return ModelResponse(
                provider="local",
                model=str(
                    self.local_fallback.config.model_path
                ),
                key_label="local-cpu",
                text=local_result.text,
                tool_calls=[],
                finish_reason="stop",
                usage={
                    "local": True,
                },
            )

    async def close(self) -> None:
        await self.gateway.close()

    def reset_context(self) -> None:
        self.history.clear()
        logger.info("Контекст Rynne очищен.")

    def provider_health(
        self,
    ) -> dict[str, Any]:
        health = self.gateway.health_snapshot()

        health["local"] = {
            "stt_configured": False,
            "llm_configured": (
                self.local_fallback.available
            ),
            "llm_model": (
                str(
                    self.local_fallback.config.model_path
                )
                if self.local_fallback.available
                else None
            ),
        }

        return health


__all__ = [
    "NovaLLM",
    "ModelResponse",
    "extract_xml_tool_calls",
]
