from __future__ import annotations

import asyncio

from modules.application.request_service import RequestService
from modules.domain.results import AssistantResponse
from modules.input_hub.coordinator import InputCoordinator
from modules.input_hub.models import UserRequest


def test_request_service_emits_orchestrator_lifecycle() -> None:
    async def scenario() -> None:
        coordinator = InputCoordinator()
        request = UserRequest.from_text("Проверь UI")
        await coordinator.submit(request)
        shutdown = asyncio.Event()
        events: list[tuple[str, dict]] = []

        class Dispatcher:
            async def dispatch(self, current_request):
                assert current_request is request
                return AssistantResponse(
                    display_text="Готово",
                    speech_text="Готово",
                )

        async def on_response(current_request, response) -> None:
            assert current_request is request
            assert response.success is True
            shutdown.set()

        service = RequestService(
            coordinator=coordinator,
            dispatcher=Dispatcher(),
            response_handler=on_response,
            event_handler=lambda event_type, payload: events.append(
                (event_type, payload)
            ),
        )
        await service.run(shutdown)

        assert [event_type for event_type, _ in events] == [
            "request_started",
            "request_completed",
        ]
        assert events[0][1]["request_id"] == request.request_id
        assert events[1][1]["success"] is True

    asyncio.run(scenario())


def test_request_interceptor_can_finish_without_dispatching() -> None:
    async def scenario() -> None:
        coordinator = InputCoordinator()
        request = UserRequest.from_voice("не сейчас", wake_word=True)
        await coordinator.submit(request)
        shutdown = asyncio.Event()
        dispatched = []
        responses = []

        class Dispatcher:
            async def dispatch(self, current_request):
                dispatched.append(current_request)
                raise AssertionError("intercepted request must not dispatch")

        async def on_response(current_request, response) -> None:
            responses.append((current_request, response))
            shutdown.set()

        service = RequestService(
            coordinator=coordinator,
            dispatcher=Dispatcher(),
            response_handler=on_response,
            request_interceptor=lambda current: AssistantResponse(
                display_text="Хорошо, не буду.",
                speech_text="Хорошо, не буду.",
            ),
        )
        await service.run(shutdown)

        assert dispatched == []
        assert responses[0][0] is request
        assert responses[0][1].display_text == "Хорошо, не буду."

    asyncio.run(scenario())
