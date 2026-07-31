# modules/application/request_service.py
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from modules.application.request_dispatcher import (
    RequestDispatcher,
)
from modules.domain.results import (
    AssistantResponse,
)
from modules.input_hub.coordinator import (
    InputCoordinator,
)
from modules.input_hub.models import (
    UserRequest,
)


logger = logging.getLogger(
    "RequestService"
)


ResponseHandler = Callable[
    [UserRequest, AssistantResponse],
    Awaitable[None],
]
RequestEnricher = Callable[
    [UserRequest],
    Any,
]
RequestInterceptor = Callable[[UserRequest], Any]


class RequestService:
    """
    Последовательно обрабатывает запросы из InputCoordinator.

    На данном этапе одновременно исполняется один запрос. Это защищает
    GUI и clipboard-инструменты от конфликтующих действий.
    """

    def __init__(
        self,
        *,
        coordinator: InputCoordinator,
        dispatcher: RequestDispatcher,
        response_handler: (
            ResponseHandler | None
        ) = None,
        event_handler: Callable[
            [str, dict[str, Any]],
            Any,
        ] | None = None,
        request_enricher: (
            RequestEnricher | None
        ) = None,
        request_interceptor: (
            RequestInterceptor | None
        ) = None,
    ) -> None:
        self.coordinator = coordinator
        self.dispatcher = dispatcher
        self.response_handler = (
            response_handler
        )
        self.event_handler = event_handler
        self.request_enricher = request_enricher
        self.request_interceptor = request_interceptor

        self._current_request: (
            UserRequest | None
        ) = None
        self._current_task: (
            asyncio.Task | None
        ) = None

    async def _emit_event(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if self.event_handler is None:
            return
        try:
            result = self.event_handler(
                event_type,
                payload,
            )
            if inspect.isawaitable(result):
                await result
        except Exception:
            # UI/телеметрия не должны ломать оркестратор запросов.
            logger.exception(
                "Не удалось отправить событие RequestService: %s.",
                event_type,
            )

    @property
    def current_request(
        self,
    ) -> UserRequest | None:
        return self._current_request

    async def run(
        self,
        shutdown_event: asyncio.Event,
    ) -> None:
        while not shutdown_event.is_set():
            request_task = asyncio.create_task(
                self.coordinator.next_request()
            )
            shutdown_task = asyncio.create_task(
                shutdown_event.wait()
            )

            done, pending = await asyncio.wait(
                {
                    request_task,
                    shutdown_task,
                },
                return_when=(
                    asyncio.FIRST_COMPLETED
                ),
            )

            for task in pending:
                task.cancel()

            await asyncio.gather(
                *pending,
                return_exceptions=True,
            )

            if shutdown_task in done:
                if not request_task.done():
                    request_task.cancel()
                break

            request = request_task.result()
            logger.info(
                "RequestService получил запрос: request_id=%s text=%r",
                (
                    request.request_id
                    if request is not None
                    else None
                ),
                (
                    request.text
                    if request is not None
                    else None
                ),
            )

            if request is None:
                self.coordinator.task_done(
                    None
                )
                break

            intercepted_response = None
            if self.request_interceptor is not None:
                try:
                    intercepted_response = self.request_interceptor(request)
                    if inspect.isawaitable(intercepted_response):
                        intercepted_response = await intercepted_response
                except Exception:
                    logger.exception(
                        "Request interceptor завершился ошибкой для %s.",
                        request.request_id,
                    )

            if isinstance(intercepted_response, AssistantResponse):
                await self._emit_event("request_started", request.to_dict())
                if self.response_handler is not None:
                    await self.response_handler(request, intercepted_response)
                await self._emit_event(
                    "request_completed",
                    {
                        "request_id": request.request_id,
                        "success": intercepted_response.success,
                        "error_code": intercepted_response.error_code,
                    },
                )
                self.coordinator.task_done(request)
                continue

            if self.request_enricher is not None:
                try:
                    enriched = self.request_enricher(
                        request
                    )
                    if inspect.isawaitable(enriched):
                        await enriched
                except Exception:
                    logger.exception(
                        "Не удалось определить workspace для запроса %s.",
                        request.request_id,
                    )

            self._current_request = request
            await self._emit_event(
                "request_started",
                request.to_dict(),
            )

            try:
                self._current_task = (
                    asyncio.create_task(
                        self.dispatcher.dispatch(
                            request
                        ),
                        name=(
                            "nova-dispatch-"
                            + request.request_id
                        ),
                    )
                )

                response = (
                    await self._current_task
                )
                logger.info(
                    (
                        "RequestService получил ответ: "
                        "request_id=%s success=%s error=%s"
                    ),
                    request.request_id,
                    response.success,
                    response.error_code,
                )

                if (
                    self.response_handler
                    is not None
                ):
                    await self.response_handler(
                        request,
                        response,
                    )
                await self._emit_event(
                    "request_completed",
                    {
                        "request_id": request.request_id,
                        "success": response.success,
                        "error_code": response.error_code,
                    },
                )

            except asyncio.CancelledError:
                if shutdown_event.is_set():
                    raise

                logger.info(
                    "Запрос %s отменён.",
                    request.request_id,
                )
                await self._emit_event(
                    "request_cancelled",
                    {
                        "request_id": request.request_id,
                        "text": request.text,
                    },
                )

            except Exception as exc:
                logger.exception(
                    "Ошибка RequestService для %s.",
                    request.request_id,
                )
                await self._emit_event(
                    "request_failed",
                    {
                        "request_id": request.request_id,
                        "text": request.text,
                        "error": str(exc),
                    },
                )

            finally:
                self._current_task = None
                self._current_request = None
                self.coordinator.task_done(
                    request
                )

    async def cancel_current(self) -> bool:
        task = self._current_task

        if task is None or task.done():
            return False

        task.cancel()

        await asyncio.gather(
            task,
            return_exceptions=True,
        )

        return True
