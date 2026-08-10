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
    configured = (
        os.getenv("RYNNE_VOSK_MODEL")
        or os.getenv("NOVA_VOSK_MODEL", "")
    ).strip()
    project_root = Path(__file__).resolve().parents[2]
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    candidates = [
        Path(configured) if configured else None,
        project_root / "data" / "vosk" / VOSK_MODEL_DIRECTORY_NAME,
        Path.cwd() / "data" / "vosk" / VOSK_MODEL_DIRECTORY_NAME,
        (
            Path(local_app_data)
            / "Rynne"
            / "models"
            / VOSK_MODEL_DIRECTORY_NAME
            if local_app_data
            else None
        ),
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

    silence_duration: float = 0.9
    maximum_command_duration: float = 20.0
    pre_roll_duration: float = 0.8

    minimum_rms_threshold: float = 0.003
    sensitivity: float = 0.72

    input_device: int | str | None = None

    @classmethod
    def from_environment(
        cls,
    ) -> "WakeWordConfig":
        model_path = discover_vosk_model_path()
        enabled_raw = (
            os.getenv("RYNNE_WAKE_WORD_ENABLED")
            or os.getenv("NOVA_WAKE_WORD_ENABLED", "")
        ).strip()
        enabled = (
            model_path is not None
            if not enabled_raw
            else enabled_raw.lower() in {"1", "true", "yes", "on"}
        )

        input_device_raw = (
            os.getenv("RYNNE_INPUT_DEVICE")
            or os.getenv("NOVA_INPUT_DEVICE", "")
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
        wake_word = (
            os.getenv("RYNNE_WAKE_WORD")
            or os.getenv("NOVA_WAKE_WORD")
            or "рин"
        ).strip().lower()
        if wake_word in {"нова", "ново", "нава", "наува", "nova"}:
            # Transparently migrate the previous brand's default without
            # requiring users to edit an existing desktop .env file.
            wake_word = "рин"
        return cls(
            enabled=enabled,
            wake_word=wake_word,
            model_path=model_path or Path(
                "__nova_vosk_model_not_configured__"
            ),
            model_configured=model_path is not None,
            maximum_command_duration=float(
                os.getenv("RYNNE_WAKE_COMMAND_TIMEOUT")
                or os.getenv("NOVA_WAKE_COMMAND_TIMEOUT", "15")
            ),
            silence_duration=float(
                os.getenv("RYNNE_WAKE_SILENCE_SECONDS")
                or os.getenv("NOVA_WAKE_SILENCE_SECONDS", "0.9")
            ),
            sensitivity=float(
                os.getenv("RYNNE_WAKE_WORD_SENSITIVITY")
                or os.getenv("NOVA_WAKE_WORD_SENSITIVITY", "0.72")
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
    duration_seconds: float = 0.0
    end_reason: str = ""

    @property
    def success(self) -> bool:
        return (
            self.detected
            and self.audio_path is not None
        )


WAKE_PREFIX_PATTERNS = (
    r"^\s*эй[\s,;:!?.-]+(?:ринн?и?|райне|rynne)[\s,;:!?.-]*",
    r"^\s*слушай[\s,;:!?.-]+(?:ринн?и?|райне|rynne)[\s,;:!?.-]*",
    r"^\s*(?:ринн?и?|райне|rynne)[\s,;:!?.-]*",
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
    wake_word: str = "рин",
) -> bool:
    normalized = normalize_wake_text(text)
    normalized_wake = normalize_wake_text(
        wake_word
    )

    if not normalized_wake:
        return False

    aliases = {normalized_wake}
    if normalized_wake == "рин":
        # Russian Vosk may stretch or transliterate the short brand name.
        aliases.update({"ринн", "ринни", "райне", "rynne"})
    # A wake word is an invocation, not an arbitrary mention halfway through
    # speech from a video. Keeping it at the beginning also avoids matching a
    # Vosk partial for the Russian adjective «новая».
    return any(
        re.search(
            rf"^(?:(?:эй|слушай)[\s,;:!?.-]+)?{re.escape(alias)}(?:$|[\s,;:!?.-])",
            normalized,
        )
        for alias in aliases
    )


def should_trigger_wake(
    text: str,
    wake_word: str = "рин",
    *,
    is_final: bool,
) -> bool:
    """Accept partial recognition only for an explicit «Эй, Рин» invocation."""
    if not contains_wake_word(text, wake_word):
        return False
    if is_final:
        return True
    normalized = normalize_wake_text(text)
    normalized_wake = normalize_wake_text(wake_word)
    strong_invocation = re.match(
        rf"^(?:эй|слушай)[\s,;:!?.-]+{re.escape(normalized_wake)}(?:$|[\s,;:!?.-])",
        normalized,
    )
    if strong_invocation:
        return True
    # A plain name waits for Vosk's final result, preventing partial phrases
    # from interrupting video or conversation audio.
    return False


def strip_wake_prefix(
    text: str,
) -> str:
    """
    Удаляет wake prefix из окончательной транскрипции.

    Примеры:
        «Рин, открой блокнот» -> «открой блокнот»
        «Эй Рин, скажи время» -> «скажи время»
        «Рин» -> ""
    """
    clean = str(text).strip()

    # STT may repeat the invocation ("Рин, Рин") or return Latin "Rynne".
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


def _abort_input_stream(stream) -> bool:
    """Discard buffered input so Windows drivers cannot stall finalization."""
    try:
        stream.abort()
        return True
    except Exception:
        logger.debug(
            "Не удалось abort wake input stream.",
            exc_info=True,
        )
        return False


def _continuation_rms_threshold(
    config: WakeWordConfig,
    *,
    noise_floor: float,
    detection_threshold: float,
) -> float:
    # The previous 0.65 multiplier put the threshold below the measured
    # background noise, so silence was mathematically impossible to reach.
    return max(
        config.minimum_rms_threshold * 1.15,
        noise_floor * 1.12,
        detection_threshold * 0.9,
    )


class WakeWordDetector:
    """
    Локальный wake-word detector на Vosk.

    Алгоритм:
    1. Постоянно читает небольшие PCM-блоки.
    2. Vosk проверяет partial/final transcription.
    3. После обнаружения обращения «Рин» продолжает записывать.
    4. После тишины сохраняет всю фразу в WAV.
    5. Основной STT повторно распознаёт WAV с высоким качеством.
    """

    def __init__(
        self,
        config: WakeWordConfig | None = None,
        activity_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        self.config = (
            config
            or WakeWordConfig.from_environment()
        )

        self._model = None
        self._model_lock = threading.RLock()
        self._initialization_error: str | None = None

        self._stop_event = threading.Event()
        self.activity_callback = activity_callback
        self._last_activity_at = 0.0

    def _emit_activity(
        self,
        phase: str,
        rms: float = 0.0,
        threshold: float = 0.008,
        *,
        force: bool = False,
    ) -> None:
        callback = self.activity_callback
        if callback is None:
            return
        now = time.monotonic()
        if not force and now - self._last_activity_at < 0.12:
            return
        self._last_activity_at = now
        level = min(1.0, max(0.0, float(rms) / max(threshold, 0.004) * 0.72))
        try:
            callback(phase, level)
        except Exception:
            logger.debug("Не удалось опубликовать wake-уровень.", exc_info=True)

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
        """Capture one wake utterance with exclusive microphone ownership."""
        from modules.input_hub.voice_owner import get_voice_owner_lock

        voice_lock = get_voice_owner_lock()
        owner_name = f"wake_word:{id(self)}"
        if not voice_lock.acquire(owner_name, allow_reentrant=False):
            return WakeCapture(
                detected=False,
                error="Микрофон переключается между голосовыми режимами.",
            )

        try:
            return self._wait_for_command_owned(should_abort)
        finally:
            self._emit_activity("idle", force=True)
            voice_lock.release(owner_name)

    def _wait_for_command_owned(
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
                "ринн"
                if self.config.wake_word == "рин"
                else self.config.wake_word
            ),
            "ринни" if self.config.wake_word == "рин" else self.config.wake_word,
            "райне" if self.config.wake_word == "рин" else self.config.wake_word,
            "rynne" if self.config.wake_word == "рин" else self.config.wake_word,
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
        end_reason = ""

        noise_floor = (
            self.config.minimum_rms_threshold
        )
        threshold = max(
            self.config.minimum_rms_threshold,
            noise_floor * 1.6,
        )

        try:
            from modules.audio.tts import is_tts_capture_blocked
            tts_was_blocked = False
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

                    if is_tts_capture_blocked():
                        self._emit_activity(
                            "paused_tts",
                            force=not tts_was_blocked,
                        )
                        # Never feed Nova's own voice or its acoustic tail to
                        # Vosk. Reset partial text so it cannot survive the
                        # playback boundary and become a false wake word.
                        if not tts_was_blocked:
                            recognizer.Reset()
                        tts_was_blocked = True
                        pre_roll.clear()
                        if wake_detected:
                            return WakeCapture(
                                detected=False,
                                error="Wake capture отменён во время TTS.",
                            )
                        continue

                    if tts_was_blocked:
                        recognizer.Reset()
                        pre_roll.clear()
                        silence_blocks = 0
                        tts_was_blocked = False

                    rms = _rms_from_bytes(
                        raw_bytes
                    )
                    self._emit_activity(
                        "recording" if wake_detected else "waiting_wake_word",
                        rms,
                        threshold,
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
                        and should_trigger_wake(
                            recognized_text,
                            self.config.wake_word,
                            is_final=accepted,
                        )
                    )
                    if just_detected:
                        wake_detected = True
                        wake_text = recognized_text
                        self._emit_activity(
                            "wake_detected",
                            rms,
                            threshold,
                            force=True,
                        )

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

                        continuation_threshold = _continuation_rms_threshold(
                            self.config,
                            noise_floor=noise_floor,
                            detection_threshold=threshold,
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
                            end_reason = "silence"
                            # PortAudio's graceful stop can wait for buffered
                            # input for minutes on some Windows Realtek drivers.
                            # The utterance is already copied, so discard the
                            # remaining device buffer before closing the stream.
                            _abort_input_stream(stream)
                            break

                        if (
                            len(captured_audio)
                            >= maximum_capture_blocks
                        ):
                            logger.info(
                                "Достигнут лимит wake-команды."
                            )
                            end_reason = "maximum_duration"
                            _abort_input_stream(stream)
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
            duration_seconds=round(
                len(captured_audio)
                * self.config.block_size
                / self.config.sample_rate,
                2,
            ),
            end_reason=end_reason or "completed",
        )
