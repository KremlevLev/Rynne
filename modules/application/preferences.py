# modules/application/preferences.py
from __future__ import annotations
import os
import logging
import threading
from dataclasses import dataclass
from typing import Any

from modules.input_hub.models import (
    AssistantProfile,
    InputMode,
    ModelSelectionMode,
)
from modules.input_hub.wake_word import WakeWordConfig


logger = logging.getLogger("Preferences")


@dataclass(slots=True)
class PreferencesSnapshot:
    input_mode: InputMode
    assistant_profile: AssistantProfile
    model_mode: ModelSelectionMode

    selected_model: str | None
    tts_enabled: bool
    cloud_enabled: bool
    history_enabled: bool
    proactive_vision_enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_mode": self.input_mode.value,
            "assistant_profile": (
                self.assistant_profile.value
            ),
            "model_mode": self.model_mode.value,
            "selected_model": self.selected_model,
            "tts_enabled": self.tts_enabled,
            "cloud_enabled": self.cloud_enabled,
            "history_enabled": self.history_enabled,
            "proactive_vision_enabled": (
                self.proactive_vision_enabled
            ),
        }


class PreferencesManager:
    """
    Потокобезопасные runtime-настройки Nova.

    Пока настройки существуют в памяти процесса. На следующем этапе
    они будут сохраняться в SQLite.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()

        wake_config = WakeWordConfig.from_environment()
        continuous_enabled = os.getenv(
            "NOVA_CONTINUOUS_LISTENING",
            "false",
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        self._input_mode = (
            InputMode.WAKE_WORD
            if (
                wake_config.available
            )
            else (
                InputMode.CONTINUOUS
                if continuous_enabled
                else InputMode.SLEEP
            )
        )

        self._assistant_profile = (
            AssistantProfile.ASSISTANT
        )
        self._model_mode = (
            ModelSelectionMode.AUTO
        )

        self._selected_model: str | None = None

        self._tts_enabled = True
        self._cloud_enabled = True
        self._history_enabled = True
        self._proactive_vision_enabled = os.getenv(
            "NOVA_PROACTIVE_VISION_ENABLED",
            "false",
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def snapshot(self) -> PreferencesSnapshot:
        with self._lock:
            return PreferencesSnapshot(
                input_mode=self._input_mode,
                assistant_profile=(
                    self._assistant_profile
                ),
                model_mode=self._model_mode,
                selected_model=(
                    self._selected_model
                ),
                tts_enabled=self._tts_enabled,
                cloud_enabled=self._cloud_enabled,
                history_enabled=(
                    self._history_enabled
                ),
                proactive_vision_enabled=(
                    self._proactive_vision_enabled
                ),
            )

    def set_input_mode(
        self,
        mode: InputMode,
    ) -> PreferencesSnapshot:
        with self._lock:
            self._input_mode = mode

            if mode == InputMode.PRIVACY:
                self._cloud_enabled = False
                self._history_enabled = False
                self._proactive_vision_enabled = False

            logger.info(
                "Режим ввода изменён: %s",
                mode.value,
            )

            return self.snapshot()

    def set_assistant_profile(
        self,
        profile: AssistantProfile,
    ) -> PreferencesSnapshot:
        with self._lock:
            self._assistant_profile = profile

            if (
                profile
                == AssistantProfile.PRIVATE_LOCAL
            ):
                self._cloud_enabled = False
                self._history_enabled = False
                self._proactive_vision_enabled = False
                self._model_mode = (
                    ModelSelectionMode.LOCAL_ONLY
                )

            logger.info(
                "Профиль Nova изменён: %s",
                profile.value,
            )

            return self.snapshot()

    def set_model_mode(
        self,
        mode: ModelSelectionMode,
        *,
        selected_model: str | None = None,
    ) -> PreferencesSnapshot:
        with self._lock:
            self._model_mode = mode

            if mode == ModelSelectionMode.PINNED:
                if not selected_model:
                    raise ValueError(
                        "Для PINNED необходимо указать модель."
                    )

                self._selected_model = (
                    selected_model.strip()
                )
            else:
                self._selected_model = None

            if (
                mode
                == ModelSelectionMode.LOCAL_ONLY
            ):
                self._cloud_enabled = False
                self._proactive_vision_enabled = False
            elif self._input_mode != InputMode.PRIVACY:
                self._cloud_enabled = True

            logger.info(
                "Режим моделей изменён: %s, model=%s",
                mode.value,
                self._selected_model,
            )

            return self.snapshot()

    def set_tts_enabled(
        self,
        enabled: bool,
    ) -> PreferencesSnapshot:
        with self._lock:
            self._tts_enabled = bool(enabled)
            return self.snapshot()

    def set_history_enabled(
        self,
        enabled: bool,
    ) -> PreferencesSnapshot:
        with self._lock:
            if self._input_mode == InputMode.PRIVACY:
                self._history_enabled = False
            else:
                self._history_enabled = bool(enabled)

            return self.snapshot()

    def set_cloud_enabled(
        self,
        enabled: bool,
    ) -> PreferencesSnapshot:
        with self._lock:
            if self._input_mode == InputMode.PRIVACY:
                self._cloud_enabled = False
                self._proactive_vision_enabled = False
            else:
                self._cloud_enabled = bool(enabled)
                if not self._cloud_enabled:
                    self._proactive_vision_enabled = False

            return self.snapshot()

    def set_proactive_vision_enabled(
        self,
        enabled: bool,
    ) -> PreferencesSnapshot:
        with self._lock:
            requested = bool(enabled)
            if requested and (
                self._input_mode == InputMode.PRIVACY
                or not self._cloud_enabled
            ):
                raise ValueError(
                    "Режим «Nova рядом» требует разрешённых "
                    "облачных vision-моделей."
                )
            self._proactive_vision_enabled = requested
            return self.snapshot()
