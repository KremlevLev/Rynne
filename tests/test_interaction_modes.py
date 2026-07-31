# tests/test_interaction_modes.py
from __future__ import annotations

import asyncio

from modules.application.interaction_modes import (
    InteractionModeManager,
)
from modules.application.preferences import (
    PreferencesManager,
)
from modules.domain.state import RuntimeState
from modules.input_hub.models import InputMode


class FakeSpeech:
    def __init__(self) -> None:
        self.interruptions = 0

    async def interrupt(self) -> None:
        self.interruptions += 1


def test_continuous_mode_activates_runtime() -> None:
    async def scenario() -> None:
        runtime = RuntimeState()
        preferences = PreferencesManager()
        speech = FakeSpeech()

        manager = InteractionModeManager(
            preferences=preferences,
            runtime=runtime,
            speech=speech,
        )

        await manager.set_mode(
            InputMode.CONTINUOUS
        )

        assert runtime.is_active
        assert (
            preferences.snapshot().input_mode
            == InputMode.CONTINUOUS
        )

    asyncio.run(scenario())


def test_wake_word_mode_sleeps_runtime() -> None:
    async def scenario() -> None:
        runtime = RuntimeState()
        preferences = PreferencesManager()

        await runtime.activate()

        manager = InteractionModeManager(
            preferences=preferences,
            runtime=runtime,
        )

        await manager.set_mode(
            InputMode.WAKE_WORD
        )

        assert not runtime.is_active
        assert (
            preferences.snapshot().input_mode
            == InputMode.WAKE_WORD
        )

    asyncio.run(scenario())


def test_text_mode_sleeps_runtime() -> None:
    async def scenario() -> None:
        runtime = RuntimeState()
        preferences = PreferencesManager()

        await runtime.activate()

        manager = InteractionModeManager(
            preferences=preferences,
            runtime=runtime,
        )

        await manager.set_mode(
            InputMode.TEXT_ONLY
        )

        assert not runtime.is_active

    asyncio.run(scenario())


def test_invalid_mode_string() -> None:
    async def scenario() -> None:
        manager = InteractionModeManager(
            preferences=PreferencesManager(),
            runtime=RuntimeState(),
        )

        try:
            await manager.set_mode_from_string(
                "invalid-mode"
            )
        except ValueError as exc:
            assert "Неизвестный режим" in str(exc)
        else:
            raise AssertionError(
                "Некорректный режим принят."
            )

    asyncio.run(scenario())


def test_mode_switch_interrupts_speech() -> None:
    async def scenario() -> None:
        speech = FakeSpeech()

        manager = InteractionModeManager(
            preferences=PreferencesManager(),
            runtime=RuntimeState(),
            speech=speech,
        )

        await manager.set_mode(
            InputMode.TEXT_ONLY
        )

        assert speech.interruptions == 1

    asyncio.run(scenario())
def test_same_wake_mode_still_synchronizes_runtime() -> None:
    async def scenario() -> None:
        runtime = RuntimeState()
        preferences = PreferencesManager()

        # Принудительно создаём рассинхронизацию:
        # настройка уже WAKE_WORD, но runtime активен.
        preferences.set_input_mode(
            InputMode.WAKE_WORD
        )
        await runtime.activate()

        manager = InteractionModeManager(
            preferences=preferences,
            runtime=runtime,
        )

        await manager.set_mode(
            InputMode.WAKE_WORD
        )

        assert not runtime.is_active
        assert (
            preferences.snapshot().input_mode
            == InputMode.WAKE_WORD
        )

    asyncio.run(scenario())
def test_same_continuous_mode_still_activates_runtime() -> None:
    async def scenario() -> None:
        runtime = RuntimeState()
        preferences = PreferencesManager()

        preferences.set_input_mode(
            InputMode.CONTINUOUS
        )

        assert not runtime.is_active

        manager = InteractionModeManager(
            preferences=preferences,
            runtime=runtime,
        )

        await manager.set_mode(
            InputMode.CONTINUOUS
        )

        assert runtime.is_active

    asyncio.run(scenario())
def test_attach_wake_runtime() -> None:
    runtime = RuntimeState()
    preferences = PreferencesManager()

    manager = InteractionModeManager(
        preferences=preferences,
        runtime=runtime,
    )

    fake_wake_runtime = object()

    manager.attach_wake_runtime(
        fake_wake_runtime
    )

    assert (
        manager.wake_runtime
        is fake_wake_runtime
    )
def test_manual_voice_returns_to_wake_word() -> None:
    async def scenario() -> None:
        runtime = RuntimeState()
        preferences = PreferencesManager()

        preferences.set_input_mode(
            InputMode.WAKE_WORD
        )

        manager = InteractionModeManager(
            preferences=preferences,
            runtime=runtime,
        )

        class FakeDetector:
            available = True

        class FakeWakeRuntime:
            detector = FakeDetector()

        manager.attach_wake_runtime(
            FakeWakeRuntime()
        )

        active, snapshot = (
            await manager.toggle_manual_voice()
        )

        assert active
        assert runtime.is_active
        assert (
            snapshot.input_mode
            == InputMode.CONTINUOUS
        )

        active, snapshot = (
            await manager.toggle_manual_voice()
        )

        assert not active
        assert not runtime.is_active
        assert (
            snapshot.input_mode
            == InputMode.WAKE_WORD
        )

    asyncio.run(scenario())


def test_manual_voice_without_wake_returns_to_sleep() -> None:
    async def scenario() -> None:
        runtime = RuntimeState()
        preferences = PreferencesManager()

        preferences.set_input_mode(
            InputMode.SLEEP
        )

        manager = InteractionModeManager(
            preferences=preferences,
            runtime=runtime,
        )

        active, _ = (
            await manager.toggle_manual_voice()
        )

        assert active
        assert runtime.is_active

        active, snapshot = (
            await manager.toggle_manual_voice()
        )

        assert not active
        assert not runtime.is_active
        assert (
            snapshot.input_mode
            == InputMode.SLEEP
        )

    asyncio.run(scenario())


def test_wake_detector_availability() -> None:
    manager = InteractionModeManager(
        preferences=PreferencesManager(),
        runtime=RuntimeState(),
    )

    assert not manager.wake_word_available

    class FakeDetector:
        available = True

    class FakeWakeRuntime:
        detector = FakeDetector()

    manager.attach_wake_runtime(
        FakeWakeRuntime()
    )

    assert manager.wake_word_available


def test_unavailable_wake_word_mode_is_rejected() -> None:
    async def scenario() -> None:
        manager = InteractionModeManager(
            preferences=PreferencesManager(),
            runtime=RuntimeState(),
        )
        manager.attach_wake_runtime(
            type(
                "UnavailableWakeRuntime",
                (),
                {"detector": type("Detector", (), {"available": False})()},
            )()
        )

        try:
            await manager.set_mode(InputMode.WAKE_WORD)
        except ValueError as exc:
            assert "Vosk" in str(exc)
        else:
            raise AssertionError("Unavailable wake word mode was enabled")

    asyncio.run(scenario())
