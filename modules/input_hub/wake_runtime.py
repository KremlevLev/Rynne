# modules/input_hub/wake_runtime.py
from __future__ import annotations

import asyncio
import logging
from modules.application.preferences import (
    PreferencesManager,
)
from modules.domain.state import (
    AssistantState,
    RuntimeState,
)
from modules.input_hub.coordinator import (
    InputCoordinator,
)
from modules.input_hub.models import (
    InputMode,
)
from modules.input_hub.wake_word import (
    WakeWordDetector,
    strip_wake_prefix,
)


logger = logging.getLogger("WakeRuntime")


class WakeWordRuntime:
    """
    Связывает WakeWordDetector с существующим VoiceListener и
    InputCoordinator.

    Wake detector записывает WAV, основной STT распознаёт всю фразу,
    wake prefix удаляется, команда отправляется в InputCoordinator.
    """

    def __init__(
        self,
        *,
        detector: WakeWordDetector,
        listener,
        coordinator: InputCoordinator,
        preferences: PreferencesManager,
        runtime: RuntimeState,
        event_handler=None,
    ) -> None:
        self.detector = detector
        self.listener = listener
        self.coordinator = coordinator
        self.preferences = preferences
        self.runtime = runtime
        self.event_handler = event_handler

        self._closed = False
        self._unavailable_logged = False

    def _publish_status(
        self,
        status: str,
        message: str,
        **payload,
    ) -> None:
        if self.event_handler is None:
            return
        self.event_handler(
            "voice_status",
            {
                "status": status,
                "message": message,
                "mode": "wake_word",
                **payload,
            },
        )

    async def run(
        self,
        shutdown_event: asyncio.Event,
    ) -> None:
        while (
            not shutdown_event.is_set()
            and not self._closed
        ):
            snapshot = (
                self.preferences.snapshot()
            )

            if (
                snapshot.input_mode
                != InputMode.WAKE_WORD
            ):
                await self._sleep_or_shutdown(
                    shutdown_event,
                    0.25,
                )
                continue

            # Если пользователь вручную включил continuous mode,
            # микрофоном владеет обычный VoiceListener.
            if self.runtime.is_active:
                await self._sleep_or_shutdown(
                    shutdown_event,
                    0.25,
                )
                continue

            if not self.detector.available:
                if not self._unavailable_logged:
                    logger.warning(
                        (
                            "Wake word включён, но detector "
                            "не настроен. Проверьте "
                            "NOVA_VOSK_MODEL."
                        )
                    )
                    self._unavailable_logged = True
                    self._publish_status(
                        "unavailable",
                        "Wake word недоступен: установите русскую Vosk-модель.",
                    )

                await self._sleep_or_shutdown(
                    shutdown_event,
                    2.0,
                )
                continue

            self._unavailable_logged = False
            self._publish_status(
                "waiting_wake_word",
                f"Жду «{self.detector.config.wake_word.title()}»…",
            )

            capture = await asyncio.to_thread(
                self.detector.wait_for_command,
                lambda: (
                    shutdown_event.is_set()
                    or self._closed
                    or (
                        self.preferences
                        .snapshot()
                        .input_mode
                        != InputMode.WAKE_WORD
                    )
                    or self.runtime.is_active
                ),
            )

            if not capture.success:
                switching_modes = (
                    capture.error
                    == "Микрофон переключается между голосовыми режимами."
                )
                if (
                    capture.error
                    and "отмен" not in (
                        capture.error.lower()
                    )
                    and "останов" not in (
                        capture.error.lower()
                    )
                ):
                    logger.debug(
                        "Wake capture: %s",
                        capture.error,
                    )

                await self._sleep_or_shutdown(
                    shutdown_event,
                    0.1 if switching_modes else 2.0,
                )
                continue

            assert capture.audio_path is not None
            self._publish_status(
                "wake_word_detected",
                (
                    f"Фраза записана за {capture.duration_seconds:.1f} сек. "
                    "Распознаю команду…"
                ),
                detected_text=capture.detected_text,
                capture_duration_seconds=capture.duration_seconds,
                capture_end_reason=capture.end_reason,
            )

            try:
                await self.runtime.set_state(
                    AssistantState.TRANSCRIBING
                )

                transcription = (
                    await asyncio.to_thread(
                        self.listener.transcribe_file,
                        capture.audio_path,
                    )
                )

            finally:
                try:
                    capture.audio_path.unlink(
                        missing_ok=True
                    )
                except OSError:
                    logger.warning(
                        (
                            "Не удалось удалить "
                            "wake audio %s."
                        ),
                        capture.audio_path,
                    )

            clean_command = strip_wake_prefix(
                transcription
            )

            if clean_command:
                logger.info(
                    "Wake-команда: %r",
                    clean_command,
                )

                request = (
                    await self.coordinator
                    .submit_voice(
                        clean_command,
                        wake_word=True,
                        metadata={
                            "wake_detected_text": (
                                capture.detected_text
                            ),
                            "full_transcription": (
                                transcription
                            ),
                        },
                    )
                )
                self._publish_status(
                    "command_recognized",
                    f"Команда: {clean_command}",
                )

                if request is None:
                    logger.warning(
                        (
                            "Wake-команда не добавлена "
                            "в очередь."
                        )
                    )

                await self.runtime.set_state(
                    AssistantState.SLEEPING
                )

            else:
                # Пользователь сказал только «Рин».
                # Захватываем ровно одну следующую фразу здесь. Раньше код
                # выставлял runtime.active, но continuous loop отключён в
                # режиме WAKE_WORD, поэтому UI говорил «слушаю» при фактически
                # закрытом микрофоне.
                logger.info(
                    (
                        "Обнаружено только wake word. "
                        "Включаю активный слух."
                    )
                )

                await self.runtime.set_state(
                    AssistantState.LISTENING
                )
                self._publish_status(
                    "listening",
                    "Да? Слушаю следующую команду…",
                )

                follow_up = await asyncio.to_thread(
                    self.listener.listen,
                    lambda: (
                        shutdown_event.is_set()
                        or self._closed
                        or self.preferences.snapshot().input_mode
                        != InputMode.WAKE_WORD
                    ),
                )

                if follow_up:
                    await self.coordinator.submit_voice(
                        follow_up,
                        wake_word=True,
                        metadata={
                            "wake_detected_text": capture.detected_text,
                            "follow_up_after_wake": True,
                        },
                    )
                    self._publish_status(
                        "command_recognized",
                        f"Команда: {follow_up}",
                    )
                else:
                    self._publish_status(
                        "waiting_wake_word",
                        f"Не расслышала команду. Жду «{self.detector.config.wake_word.title()}»…",
                    )

                await self.runtime.set_state(
                    AssistantState.SLEEPING
                )

    async def _sleep_or_shutdown(
        self,
        shutdown_event: asyncio.Event,
        timeout: float,
    ) -> None:
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            pass

    def close(self) -> None:
        self._closed = True
        self.detector.stop()
