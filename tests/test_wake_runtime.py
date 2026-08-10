from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from modules.domain.state import RuntimeState
from modules.input_hub.models import InputMode
from modules.input_hub.wake_runtime import WakeWordRuntime
from modules.input_hub.wake_word import WakeCapture


def test_wake_only_phrase_opens_real_one_shot_follow_up(tmp_path: Path) -> None:
    async def scenario() -> None:
        audio_path = tmp_path / "wake.wav"
        audio_path.write_bytes(b"test")
        shutdown = asyncio.Event()

        class Detector:
            available = True
            config = SimpleNamespace(wake_word="рин")

            def wait_for_command(self, _should_abort):
                return WakeCapture(
                    detected=True,
                    audio_path=audio_path,
                    detected_text="рин",
                )

            def stop(self) -> None:
                pass

        class Listener:
            follow_up_calls = 0

            def transcribe_file(self, _path) -> str:
                return "Рин"

            def listen(self, _should_abort) -> str:
                self.follow_up_calls += 1
                return "открой браузер"

        class Coordinator:
            submissions: list[tuple[str, bool, dict]] = []

            async def submit_voice(self, text, *, wake_word, metadata):
                self.submissions.append((text, wake_word, metadata))
                shutdown.set()
                return object()

        class Preferences:
            def snapshot(self):
                return SimpleNamespace(input_mode=InputMode.WAKE_WORD)

        listener = Listener()
        coordinator = Coordinator()
        runtime = RuntimeState()
        service = WakeWordRuntime(
            detector=Detector(),
            listener=listener,
            coordinator=coordinator,
            preferences=Preferences(),
            runtime=runtime,
        )

        await asyncio.wait_for(service.run(shutdown), timeout=2.0)

        assert listener.follow_up_calls == 1
        assert coordinator.submissions == [
            (
                "открой браузер",
                True,
                {
                    "wake_detected_text": "рин",
                    "follow_up_after_wake": True,
                },
            )
        ]
        assert not runtime.is_active

    asyncio.run(scenario())
