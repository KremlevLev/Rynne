# modules/application/interaction_modes.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.application.preferences import (
    PreferencesManager,
    PreferencesSnapshot,
)
from modules.domain.state import RuntimeState
from modules.input_hub.models import InputMode


logger = logging.getLogger("InteractionModes")


class InteractionModeManager:
    """
    Единая точка переключения режимов взаимодействия Nova.

    Не изменяйте InputMode напрямую через PreferencesManager,
    если доступен InteractionModeManager.
    """

    def __init__(
        self,
        *,
        preferences: PreferencesManager,
        runtime: RuntimeState,
        speech=None,
        wake_runtime=None,
    ) -> None:
        self.preferences = preferences
        self.runtime = runtime
        self.speech = speech
        self.wake_runtime = wake_runtime

        self._lock = asyncio.Lock()
        # Режим, в который нужно вернуться после завершения
        # временной голосовой сессии по горячей клавише.
        self._manual_return_mode: InputMode | None = None

    def attach_wake_runtime(
        self,
        wake_runtime,
    ) -> None:
        """
        Подключает WakeWordRuntime после его создания.

        InteractionModeManager создаётся раньше WakeWordRuntime,
        поэтому зависимость подключается отдельно после bootstrap.
        """
        self.wake_runtime = wake_runtime

        logger.info(
            "WakeWordRuntime подключён к менеджеру режимов."
        )
    @property
    def wake_word_available(self) -> bool:
        """
        Проверяет, настроен ли реальный wake-word detector.
        """
        wake_runtime = self.wake_runtime

        if wake_runtime is None:
            return False

        detector = getattr(
            wake_runtime,
            "detector",
            None,
        )

        return bool(
            detector is not None
            and detector.available
        )

    async def toggle_manual_voice(
        self,
    ) -> tuple[bool, PreferencesSnapshot]:
        """
        Переключает ручную голосовую сессию по горячей клавише.

        Первое нажатие:
            WAKE_WORD/SLEEP/TEXT_ONLY -> CONTINUOUS

        Второе нажатие:
            CONTINUOUS -> прежний режим

        Если прежний режим неизвестен, но wake word настроен,
        Nova возвращается в WAKE_WORD.
        """
        snapshot = self.preferences.snapshot()

        if (
            snapshot.input_mode
            == InputMode.CONTINUOUS
            and self.runtime.is_active
        ):
            return_mode = (
                self._manual_return_mode
            )

            if return_mode is None:
                return_mode = (
                    InputMode.WAKE_WORD
                    if self.wake_word_available
                    else InputMode.SLEEP
                )

            # Не возвращаемся в CONTINUOUS из CONTINUOUS.
            if return_mode == InputMode.CONTINUOUS:
                return_mode = (
                    InputMode.WAKE_WORD
                    if self.wake_word_available
                    else InputMode.SLEEP
                )

            self._manual_return_mode = None

            updated_snapshot = (
                await self.set_mode(
                    return_mode
                )
            )

            logger.info(
                (
                    "Ручная голосовая сессия выключена. "
                    "Возврат в режим %s."
                ),
                return_mode.value,
            )

            return False, updated_snapshot

        current_mode = snapshot.input_mode

        # Запоминаем режим, который был активен до горячей клавиши.
        if current_mode != InputMode.CONTINUOUS:
            self._manual_return_mode = (
                current_mode
            )
        elif self.wake_word_available:
            self._manual_return_mode = (
                InputMode.WAKE_WORD
            )
        else:
            self._manual_return_mode = (
                InputMode.SLEEP
            )

        updated_snapshot = (
            await self.set_mode(
                InputMode.CONTINUOUS
            )
        )

        logger.info(
            (
                "Ручная голосовая сессия включена. "
                "Режим возврата: %s."
            ),
            self._manual_return_mode.value,
        )

        return True, updated_snapshot

    async def set_mode(
        self,
        mode: InputMode,
    ) -> PreferencesSnapshot:
        """
        Устанавливает режим и синхронизирует RuntimeState.

        Метод намеренно применяет состояние runtime даже тогда,
        когда выбранный InputMode уже записан в PreferencesManager.
        Это исправляет рассинхронизацию вида:

            preferences = WAKE_WORD
            runtime = active
        """
        if (
            mode == InputMode.WAKE_WORD
            and self.wake_runtime is not None
            and not self.wake_word_available
        ):
            raise ValueError(
                "Wake word недоступен: установите русскую Vosk-модель "
                "командой `python -m vosk_install` и перезапустите Nova Core."
            )

        async with self._lock:
            previous_mode = (
                self.preferences
                .snapshot()
                .input_mode
            )

            mode_changed = (
                previous_mode != mode
            )

            if mode_changed:
                logger.info(
                    "Переключение режима: %s -> %s",
                    previous_mode.value,
                    mode.value,
                )

                if self.speech is not None:
                    await self.speech.interrupt()

                snapshot = (
                    self.preferences.set_input_mode(
                        mode
                    )
                )
            else:
                logger.debug(
                    (
                        "Режим %s уже выбран. "
                        "Синхронизирую RuntimeState."
                    ),
                    mode.value,
                )

                snapshot = (
                    self.preferences.snapshot()
                )

            # CONTINUOUS — единственный режим, в котором обычный
            # VoiceListener должен непрерывно слушать микрофон.
            if mode == InputMode.CONTINUOUS:
                if not self.runtime.is_active:
                    await self.runtime.activate()

            else:
                # WAKE_WORD слушает через отдельный лёгкий detector.
                # PUSH_TO_TALK ждёт удержания горячей клавиши.
                # TEXT_ONLY, PRIVACY и SLEEP не используют
                # непрерывный VoiceListener.
                if self.runtime.is_active:
                    await self.runtime.sleep()
                else:
                    # Даже при уже неактивном runtime обновляем
                    # визуальное состояние на СПИТ.
                    await self.runtime.sleep()

            return snapshot


    async def set_mode_from_string(
        self,
        mode_name: str,
    ) -> PreferencesSnapshot:
        try:
            mode = InputMode(
                mode_name.strip().lower()
            )
        except ValueError as exc:
            valid_modes = ", ".join(
                mode.value
                for mode in InputMode
            )

            raise ValueError(
                (
                    f"Неизвестный режим '{mode_name}'. "
                    f"Допустимые режимы: {valid_modes}."
                )
            ) from exc

        return await self.set_mode(mode)

    def snapshot(self) -> dict[str, Any]:
        return (
            self.preferences
            .snapshot()
            .to_dict()
        )
