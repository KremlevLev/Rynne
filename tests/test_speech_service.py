# tests/test_speech_service.py
from __future__ import annotations

import asyncio
import threading
import time

import modules.application.speech as speech_module
from modules.application.speech import (
    SpeechService,
    prepare_text_for_speech,
    split_speech_chunks,
)
from modules.domain.state import RuntimeState


def test_markdown_table_is_not_spoken() -> None:
    source = """
| Действие | Команда |
|---|---|
| Открыть | Ctrl+O |
| Закрыть | Ctrl+W |
"""

    prepared = prepare_text_for_speech(source)

    assert "Ctrl+O" not in prepared
    assert "Ctrl+W" not in prepared
    assert "таблице на экране" in prepared


def test_long_text_is_shortened() -> None:
    source = "Очень длинный ответ. " * 200

    prepared = prepare_text_for_speech(
        source,
        max_total_characters=300,
    )

    assert len(prepared) < 400
    assert "Подробности показаны на экране" in prepared


def test_speech_chunks_respect_limit() -> None:
    source = (
        "Первое предложение. "
        "Второе предложение. "
        + ("очень длинный текст " * 100)
    )

    chunks = split_speech_chunks(
        source,
        max_chunk_characters=120,
    )

    assert chunks
    assert all(len(chunk) <= 120 for chunk in chunks)


def test_start_does_not_warm_heavy_local_tts_by_default(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        warmup_started = threading.Event()

        monkeypatch.setattr(
            speech_module,
            "warm_up_tts",
            lambda: warmup_started.set(),
        )

        service = SpeechService(RuntimeState())
        await service.start()
        await asyncio.sleep(0)

        assert not warmup_started.is_set()

        await service.close()

    asyncio.run(scenario())


def test_explicit_start_warms_tts_and_publishes_ready(monkeypatch) -> None:
    async def scenario() -> None:
        events: list[tuple[str, dict]] = []
        monkeypatch.setattr(speech_module, "warm_up_tts", lambda: True)
        service = SpeechService(
            RuntimeState(),
            event_handler=lambda event_type, payload: events.append((event_type, payload)),
            warm_up_on_start=True,
        )

        await service.start()
        assert service._warmup_task is not None
        assert await service._warmup_task is True
        assert [payload["status"] for event, payload in events if event == "voice_status"] == [
            "loading", "ready",
        ]
        await service.close()

    asyncio.run(scenario())


def test_interrupt_does_not_cancel_caller(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        started_speaking = threading.Event()
        stopped_speaking = threading.Event()

        def fake_speak(text: str) -> None:
            started_speaking.set()

            # Эмулируем блокирующее воспроизведение.
            stopped_speaking.wait(timeout=3.0)

        def fake_stop_speaking() -> None:
            stopped_speaking.set()

        def fake_reset_interrupt_flag() -> None:
            pass

        monkeypatch.setattr(
            speech_module,
            "speak",
            fake_speak,
        )
        monkeypatch.setattr(
            speech_module,
            "stop_speaking",
            fake_stop_speaking,
        )
        monkeypatch.setattr(
            speech_module,
            "reset_interrupt_flag",
            fake_reset_interrupt_flag,
        )

        runtime = RuntimeState()
        await runtime.activate()

        service = SpeechService(runtime)
        await service.start()

        say_task = asyncio.create_task(
            service.say(
                "Это длинное тестовое сообщение.",
                wait=True,
            )
        )

        # Ждем начала fake_speak, не блокируя event loop.
        started = await asyncio.to_thread(
            started_speaking.wait,
            2.0,
        )

        assert started

        await service.interrupt()

        # say() должен завершиться нормально, а не CancelledError.
        await asyncio.wait_for(
            say_task,
            timeout=2.0,
        )

        assert not say_task.cancelled()
        assert say_task.exception() is None

        await service.close()

    asyncio.run(scenario())


def test_multiple_interrupts_are_safe(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        def fake_speak(text: str) -> None:
            time.sleep(0.01)

        def fake_stop_speaking() -> None:
            pass

        monkeypatch.setattr(
            speech_module,
            "speak",
            fake_speak,
        )
        monkeypatch.setattr(
            speech_module,
            "stop_speaking",
            fake_stop_speaking,
        )
        monkeypatch.setattr(
            speech_module,
            "reset_interrupt_flag",
            lambda: None,
        )

        runtime = RuntimeState()
        await runtime.activate()

        service = SpeechService(runtime)
        await service.start()

        await service.interrupt()
        await service.interrupt()
        await service.interrupt()

        await service.say(
            "После прерываний сервис продолжает работать.",
            wait=True,
        )

        assert service.is_running

        await service.close()

    asyncio.run(scenario())
