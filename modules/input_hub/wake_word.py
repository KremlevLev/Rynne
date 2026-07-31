# modules/input_hub/wake_word.py
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from dotenv import load_dotenv
import numpy as np
import sounddevice as sd


logger = logging.getLogger("WakeWord")
load_dotenv()


VOSK_MODEL_DIRECTORY_NAME = "vosk-model-small-ru-0.22"


def discover_vosk_model_path() -> Path | None:
    """Find a configured or locally installed Russian Vosk model."""
    configured = os.getenv("NOVA_VOSK_MODEL", "").strip()
    project_root = Path(__file__).resolve().parents[2]
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    candidates = [
        Path(configured) if configured else None,
        project_root / "data" / "vosk" / VOSK_MODEL_DIRECTORY_NAME,
        Path.cwd() / "data" / "vosk" / VOSK_MODEL_DIRECTORY_NAME,
        (
            Path(local_app_data)
            / "Nova"
            / "models"
            / VOSK_MODEL_DIRECTORY_NAME
            if local_app_data
            else None
        ),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_dir():
            return candidate.resolve()
    return None


@dataclass(slots=True)
class WakeWordConfig:
    enabled: bool
    wake_word: str
    model_path: Path
    model_configured: bool = False

    sample_rate: int = 16_000
    block_size: int = 1_024

    silence_duration: float = 0.85
    maximum_command_duration: float = 15.0
    pre_roll_duration: float = 0.8

    minimum_rms_threshold: float = 0.003
    sensitivity: float = 0.72

    input_device: int | str | None = None

    @classmethod
    def from_environment(
        cls,
    ) -> "WakeWordConfig":
        model_path = discover_vosk_model_path()
        enabled_raw = os.getenv("NOVA_WAKE_WORD_ENABLED", "").strip()
        enabled = (
            model_path is not None
            if not enabled_raw
            else enabled_raw.lower() in {"1", "true", "yes", "on"}
        )

        input_device_raw = os.getenv(
            "NOVA_INPUT_DEVICE",
            "",
        ).strip()

        input_device: int | str | None

        if not input_device_raw:
            input_device = None
        elif input_device_raw.isdigit():
            input_device = int(
                input_device_raw
            )
        else:
            input_device = input_device_raw
        return cls(
            enabled=enabled,
            wake_word=os.getenv(
                "NOVA_WAKE_WORD",
                "нова",
            ).strip().lower(),
            model_path=model_path or Path(
                "__nova_vosk_model_not_configured__"
            ),
            model_configured=model_path is not None,
            maximum_command_duration=float(
                os.getenv(
                    "NOVA_WAKE_COMMAND_TIMEOUT",
                    "15",
                )
            ),
            sensitivity=float(
                os.getenv(
                    "NOVA_WAKE_WORD_SENSITIVITY",
                    "0.72",
                )
            ),
            input_device=input_device,
        )

    @property
    def available(self) -> bool:
        return (
            self.enabled
            and bool(self.wake_word)
            and self.model_configured
            and self.model_path.is_dir()
        )



@dataclass(slots=True)
class WakeCapture:
    detected: bool
    audio_path: Path | None = None
    detected_text: str = ""
    error: str = ""

    @property
    def success(self) -> bool:
        return (
            self.detected
            and self.audio_path is not None
        )


WAKE_PREFIX_PATTERNS = (
    r"^\s*эй[\s,;:!?.-]+нов[ао][\s,;:!?.-]*",
    r"^\s*слушай[\s,;:!?.-]+нов[ао][\s,;:!?.-]*",
    r"^\s*(?:нов[ао]|наува|новчик|nova)[\s,;:!?.-]*",
)


def normalize_wake_text(
    text: str,
) -> str:
    normalized = str(text).lower()
    normalized = normalized.replace(
        "ё",
        "е",
    )
    normalized = re.sub(
        r"\s+",
        " ",
        normalized,
    )

    return normalized.strip()


def contains_wake_word(
    text: str,
    wake_word: str = "нова",
) -> bool:
    normalized = normalize_wake_text(text)
    normalized_wake = normalize_wake_text(
        wake_word
    )

    if not normalized_wake:
        return False

    aliases = {normalized_wake}
    if normalized_wake == "нова":
        # Small Russian Vosk models sometimes finalize «Нова» as «ново».
        aliases.add("ново")
    return any(
        re.search(rf"\b{re.escape(alias)}\b", normalized)
        for alias in aliases
    )


def strip_wake_prefix(
    text: str,
) -> str:
    """
    Удаляет wake prefix из окончательной транскрипции.

    Примеры:
        «Нова, открой блокнот» -> «открой блокнот»
        «Эй Нова, скажи время» -> «скажи время»
        «Нова» -> ""
    """
    clean = str(text).strip()

    # STT may repeat the invocation ("Нова, Нова") or return Latin "Nova".
    # Remove every leading invocation so a wake-only utterance never becomes
    # an accidental LLM request.
    changed = True
    while clean and changed:
        changed = False
        for pattern in WAKE_PREFIX_PATTERNS:
            updated = re.sub(
                pattern,
                "",
                clean,
                count=1,
                flags=re.IGNORECASE,
            )
            if updated != clean:
                clean = updated.strip(" \t\r\n,;:!?.-")
                changed = True
                break

    return clean.strip()


def _rms_from_bytes(
    raw_audio: bytes,
) -> float:
    if not raw_audio:
        return 0.0

    samples = np.frombuffer(
        raw_audio,
        dtype=np.int16,
    ).astype(np.float32)

    if samples.size == 0:
        return 0.0

    samples /= 32768.0

    return float(
        np.sqrt(
            np.mean(
                np.square(samples)
            )
        )
    )


class WakeWordDetector:
    """
    Локальный wake-word detector на Vosk.

    Алгоритм:
    1. Постоянно читает небольшие PCM-блоки.
    2. Vosk проверяет partial/final transcription.
    3. После обнаружения слова «Нова» продолжает записывать.
    4. После тишины сохраняет всю фразу в WAV.
    5. Основной STT повторно распознаёт WAV с высоким качеством.
    """

    def __init__(
        self,
        config: WakeWordConfig | None = None,
    ) -> None:
        self.config = (
            config
            or WakeWordConfig.from_environment()
        )

        self._model = None
        self._model_lock = threading.RLock()
        self._initialization_error: str | None = None

        self._stop_event = threading.Event()

    @property
    def available(self) -> bool:
        return self.config.available

    def stop(self) -> None:
        self._stop_event.set()

    def reset(self) -> None:
        self._stop_event.clear()

    def _load_model(self):
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            try:
                from vosk import Model
            except ImportError as exc:
                raise RuntimeError(
                    (
                        "Vosk не установлен. Выполните: "
                        "py -m pip install vosk"
                    )
                ) from exc

            if not self.config.model_path.is_dir():
                raise RuntimeError(
                    (
                        "Vosk-модель не найдена: "
                        f"{self.config.model_path}"
                    )
                )

            logger.info(
                "Загрузка Vosk wake-word модели: %s",
                self.config.model_path,
            )

            self._model = Model(
                str(self.config.model_path)
            )

            logger.info(
                "Vosk wake-word модель загружена."
            )

            return self._model

    @staticmethod
    def _extract_vosk_text(
        payload: str,
    ) -> str:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return ""

        return str(
            parsed.get("text")
            or parsed.get("partial")
            or ""
        ).strip()

    def wait_for_command(
        self,
        should_abort: Callable[
            [],
            bool,
        ] | None = None,
    ) -> WakeCapture:
        if not self.available:
            return WakeCapture(
                detected=False,
                error=(
                    "Wake word отключён или "
                    "Vosk-модель не настроена."
                ),
            )
        if self._initialization_error is not None:
            return WakeCapture(
                detected=False,
                error=self._initialization_error,
            )

        self.reset()

        try:
            from vosk import (
                KaldiRecognizer,
                SetLogLevel,
            )

            SetLogLevel(-1)
            model = self._load_model()

        except Exception as exc:
            self._initialization_error = str(exc)
            logger.exception(
                "Не удалось подготовить wake word."
            )

            return WakeCapture(
                detected=False,
                error=str(exc),
            )

        wake_grammar = [
            self.config.wake_word,
            f"эй {self.config.wake_word}",
            f"слушай {self.config.wake_word}",
            (
                "ново"
                if self.config.wake_word == "нова"
                else self.config.wake_word
            ),
            "[unk]",
        ]
        recognizer = KaldiRecognizer(
            model,
            self.config.sample_rate,
            json.dumps(wake_grammar, ensure_ascii=False),
        )

        stream_arguments = {
            "samplerate": (
                self.config.sample_rate
            ),
            "channels": 1,
            "blocksize": (
                self.config.block_size
            ),
            "dtype": "int16",
        }

        if self.config.input_device is not None:
            stream_arguments["device"] = (
                self.config.input_device
            )

        pre_roll_blocks = max(
            1,
            int(
                self.config.pre_roll_duration
                * self.config.sample_rate
                / self.config.block_size
            ),
        )

        silence_limit_blocks = max(
            1,
            int(
                self.config.silence_duration
                * self.config.sample_rate
                / self.config.block_size
            ),
        )

        maximum_capture_blocks = max(
            1,
            int(
                self.config.maximum_command_duration
                * self.config.sample_rate
                / self.config.block_size
            ),
        )

        pre_roll: deque[bytes] = deque(
            maxlen=pre_roll_blocks
        )

        captured_audio: list[bytes] = []

        wake_detected = False
        wake_text = ""

        silence_blocks = 0
        post_wake_blocks = 0

        noise_floor = (
            self.config.minimum_rms_threshold
        )
        threshold = max(
            self.config.minimum_rms_threshold,
            noise_floor * 1.6,
        )

        try:
            with sd.RawInputStream(
                **stream_arguments
            ) as stream:
                logger.info(
                    (
                        "Wake word активен. "
                        "Ожидаю фразу '%s'."
                    ),
                    self.config.wake_word,
                )

                while True:
                    if self._stop_event.is_set():
                        return WakeCapture(
                            detected=False,
                            error="Wake detector остановлен.",
                        )

                    if (
                        should_abort is not None
                        and should_abort()
                    ):
                        return WakeCapture(
                            detected=False,
                            error="Wake detector отменён.",
                        )

                    audio_block, overflowed = (
                        stream.read(
                            self.config.block_size
                        )
                    )

                    raw_bytes = bytes(audio_block)

                    if overflowed:
                        logger.debug(
                            "Wake-word audio overflow."
                        )

                    rms = _rms_from_bytes(
                        raw_bytes
                    )

                    if not wake_detected:
                        pre_roll.append(
                            raw_bytes
                        )

                        noise_floor = (
                            noise_floor * 0.995
                            + rms * 0.005
                        )

                        sensitivity = min(
                            1.0,
                            max(
                                0.0,
                                self.config.sensitivity,
                            ),
                        )
                        threshold = max(
                            (
                                self.config
                                .minimum_rms_threshold
                            ),
                            noise_floor * (1.65 - sensitivity * 0.5),
                        )

                    accepted = (
                        recognizer.AcceptWaveform(
                            raw_bytes
                        )
                    )

                    if accepted:
                        recognized_text = (
                            self._extract_vosk_text(
                                recognizer.Result()
                            )
                        )
                    else:
                        recognized_text = (
                            self._extract_vosk_text(
                                recognizer.PartialResult()
                            )
                        )

                    just_detected = (
                        not wake_detected
                        and contains_wake_word(
                            recognized_text,
                            self.config.wake_word,
                        )
                    )
                    if just_detected:
                        wake_detected = True
                        wake_text = recognized_text

                        captured_audio.extend(
                            list(pre_roll)
                        )

                        logger.info(
                            (
                                "Wake word обнаружен: "
                                "text=%r rms=%.4f"
                            ),
                            recognized_text,
                            rms,
                        )

                    if wake_detected:
                        # The detection block is already present in pre-roll.
                        if not just_detected:
                            captured_audio.append(raw_bytes)

                        post_wake_blocks += 1

                        continuation_threshold = max(
                            (
                                self.config
                                .minimum_rms_threshold
                            ),
                            threshold * 0.65,
                        )

                        if rms > continuation_threshold:
                            silence_blocks = 0
                        else:
                            silence_blocks += 1

                        # Не завершаем запись сразу после wake word:
                        # даём пользователю произнести продолжение.
                        minimum_post_wake_blocks = max(
                            2,
                            int(
                                0.5
                                * self.config.sample_rate
                                / self.config.block_size
                            ),
                        )

                        if (
                            post_wake_blocks
                            >= minimum_post_wake_blocks
                            and silence_blocks
                            >= silence_limit_blocks
                        ):
                            break

                        if (
                            len(captured_audio)
                            >= maximum_capture_blocks
                        ):
                            logger.info(
                                "Достигнут лимит wake-команды."
                            )
                            break

        except sd.PortAudioError as exc:
            logger.error(
                "Ошибка микрофона wake word: %s",
                exc,
            )

            return WakeCapture(
                detected=False,
                error=str(exc),
            )

        except Exception as exc:
            logger.exception(
                "Ошибка wake-word цикла."
            )

            return WakeCapture(
                detected=False,
                error=str(exc),
            )

        if not wake_detected:
            return WakeCapture(
                detected=False,
                error="Wake word не обнаружен.",
            )

        if not captured_audio:
            return WakeCapture(
                detected=False,
                error="Wake audio пуст.",
            )

        temp_directory = Path(
            "data/temp"
        )
        temp_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_descriptor, raw_path = (
            tempfile.mkstemp(
                prefix="nova_wake_",
                suffix=".wav",
                dir=str(temp_directory),
            )
        )

        os.close(file_descriptor)

        audio_path = Path(raw_path)

        try:
            with wave.open(
                str(audio_path),
                "wb",
            ) as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(
                    self.config.sample_rate
                )

                wav_file.writeframes(
                    b"".join(captured_audio)
                )

        except Exception as exc:
            audio_path.unlink(
                missing_ok=True
            )

            return WakeCapture(
                detected=False,
                error=(
                    "Не удалось сохранить wake audio: "
                    f"{exc}"
                ),
            )

        return WakeCapture(
            detected=True,
            audio_path=audio_path,
            detected_text=wake_text,
        )
