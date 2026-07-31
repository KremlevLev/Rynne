# modules/application/request_dispatcher.py
from __future__ import annotations

import logging
from typing import Any

from modules.application.agent import (
    AgentService,
)
from modules.domain.results import (
    AssistantResponse,
)
from modules.input_hub.models import (
    UserRequest,
)
from modules.routing.decision import (
    ExecutionStrategy,
)
from modules.routing.direct_executor import (
    DirectRequestExecutor,
)
from modules.routing.intent import (
    DeterministicIntentRouter,
)


logger = logging.getLogger(
    "RequestDispatcher"
)


class RequestDispatcher:
    """
    Центральный диспетчер запросов Nova.

    DIRECT без инструментов:
        локальные настройки выполняются через DirectRequestExecutor.

    Любое действие с инструментами:
        передаётся AgentService, даже если router уверен в одном atomic tool.
        Router задаёт capability hints и safety, но не перехватывает цель.

    CLARIFY:
        возвращается локальный уточняющий вопрос.

    DENY:
        возвращается локальный отказ.

    CHAT / SKILL / WORKFLOW / PLAN:
        передаются AgentService.
    """

    def __init__(
        self,
        *,
        agent: AgentService,
        direct_executor: DirectRequestExecutor,
        intent_router: (
            DeterministicIntentRouter | None
        ) = None,
    ) -> None:
        self.agent = agent
        self.direct_executor = direct_executor
        self.intent_router = (
            intent_router
            or DeterministicIntentRouter()
        )

    def _remember_non_agent_turn(
        self,
        request: UserRequest,
        response: AssistantResponse,
    ) -> None:
        recorder = getattr(
            self.agent,
            "record_external_turn",
            None,
        )
        if callable(recorder):
            recorder(
                request.text,
                response.display_text,
            )

    async def dispatch(
        self,
        request: UserRequest,
    ) -> AssistantResponse:
        if request.is_empty:
            return AssistantResponse(
                display_text=(
                    "Запрос не содержит текста "
                    "или вложений."
                ),
                speech_text=(
                    "Сэр, запрос пуст."
                ),
                success=False,
                error_code="EMPTY_REQUEST",
                data={
                    "request_id": (
                        request.request_id
                    ),
                    "model_calls": 0,
                },
            )

        decision = self.intent_router.route(
            request
        )

        logger.info(
            (
                "Dispatch request: request_id=%s "
                "source=%s strategy=%s intent=%s"
            ),
            request.request_id,
            request.source.value,
            decision.strategy.value,
            decision.intent.value,
        )

        if (
            decision.strategy
            == ExecutionStrategy.DIRECT
            and not request.has_image
            and not decision.needs_tools
        ):
            response = (
                await self.direct_executor.execute(
                    request,
                    decision,
                )
            )

            response.data.setdefault(
                "request_id",
                request.request_id,
            )
            response.data.setdefault(
                "execution_decision",
                decision.to_dict(),
            )
            response.data.setdefault(
                "model_calls",
                0,
            )

            self._remember_non_agent_turn(
                request,
                response,
            )
            return response

        if (
            decision.strategy
            == ExecutionStrategy.CLARIFY
        ):
            question = (
                decision.clarification_question
                or "Уточните запрос."
            )

            response = AssistantResponse(
                display_text=question,
                speech_text=question,
                success=False,
                error_code=(
                    "CLARIFICATION_REQUIRED"
                ),
                data={
                    "request_id": (
                        request.request_id
                    ),
                    "execution_decision": (
                        decision.to_dict()
                    ),
                    "model_calls": 0,
                },
            )
            self._remember_non_agent_turn(
                request,
                response,
            )
            return response

        if (
            decision.strategy
            == ExecutionStrategy.DENY
        ):
            reason = (
                decision.denial_reason
                or "Запрос запрещён."
            )

            response = AssistantResponse(
                display_text=reason,
                speech_text=reason,
                success=False,
                error_code="REQUEST_DENIED",
                data={
                    "request_id": (
                        request.request_id
                    ),
                    "execution_decision": (
                        decision.to_dict()
                    ),
                    "model_calls": 0,
                },
            )
            self._remember_non_agent_turn(
                request,
                response,
            )
            return response

        try:
            response = await self.agent.run(
                request,
                use_tools=decision.needs_tools,
                has_image=request.has_image,
            )

        except Exception as exc:
            logger.exception(
                "AgentService завершился ошибкой."
            )

            return AssistantResponse(
                display_text=(
                    "Внутренняя ошибка обработки "
                    f"запроса: {exc}"
                ),
                speech_text=(
                    "Сэр, запрос завершился "
                    "внутренней ошибкой."
                ),
                success=False,
                error_code=(
                    "REQUEST_DISPATCH_FAILED"
                ),
                data={
                    "request_id": (
                        request.request_id
                    ),
                    "execution_decision": (
                        decision.to_dict()
                    ),
                },
            )

        response.data.setdefault(
            "request_id",
            request.request_id,
        )
        response.data.setdefault(
            "execution_decision",
            decision.to_dict(),
        )

        return response
