# modules/audio/stt.py
from __future__ import annotations
import re
import logging
import os
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from modules.local.inference import (
    LocalSTTFallback,
)
import numpy as np
import requests
import sounddevice as sd
import asyncio
from core.config import GROQ_API_KEYS


logger = logging.getLogger("STT")


WHISPER_HALLUCINATIONS = {
    "спасибо",
    "спасибо.",
    "спасибо за внимание",
    "спасибо за просмотр",
    "продолжение следует",
    "минут",
    "вы",
    "я",
    "пожалуйста",
    "пожалуйста.",
    "просмотр",
    "субтитры",
    "продолжение",
    "тревожная музыка",
    "фоновая музыка",
    "музыка",
    "приятного просмотра",
}

WHISPER_HALLUCINATION_PATTERNS = (
    r"^субтитры\s+(?:создавал|создала|сделал|сделала|подготовил|подготовила|редактор|автор).*$",
    r"^(?:редактор|автор|переводчик)\s+субтитров.*$",
    r"^(?:тревожная|фоновая|веселая|грустная|эпичная)\s+музыка$",
    r"^\[?\s*музыка\s*\]?$",
)


def is_likely_whisper_hallucination(text: str) -> bool:
    normalized = re.sub(
        r"\s+",
        " ",
        str(text).lower().replace("ё", "е"),
    ).strip(" \t\r\n.!?…,:;—–-()[]{}\"'«»")
    if not normalized:
        return True
    if normalized in WHISPER_HALLUCINATIONS:
        return True
    return any(
        re.fullmatch(pattern, normalized, flags=re.IGNORECASE)
        for pattern in WHISPER_HALLUCINATION_PATTERNS
    )

KNOWN_APPLICATION_NAMES = (
    "obsidian",
    "обсидиан",
    "discord",
    "дискорд",
    "telegram",
    "телеграм",
    "chrome",
    "хром",
    "visual studio code",
    "вс код",
    "блокнот",
    "калькулятор",
    "проводник",
)


def normalize_voice_command(text: str) -> str:
    """
    Исправляет только характерные ошибки Whisper в начале команды.

    Коррекция применяется лишь при наличии известного приложения,
    чтобы обычный вопрос «какие клавиши Obsidian» не превратился
    в команду запуска.
    """
    clean = re.sub(r"\s+", " ", text.strip())
    lowered = clean.lower().replace("ё", "е")

    contains_known_application = any(
        app_name in lowered
        for app_name in KNOWN_APPLICATION_NAMES
    )

    if not contains_known_application:
        return clean

    command_corrections = (
        (r"^\s*ключи\s+", "Включи "),
        (r"^\s*в ключи\s+", "Включи "),
        (r"^\s*включить\s+", "Включи "),
        (r"^\s*откройте\s+", "Открой "),
        (r"^\s*запустим\s+", "Запусти "),
    )

    for pattern, replacement in command_corrections:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            corrected = re.sub(
                pattern,
                replacement,
                clean,
                count=1,
                flags=re.IGNORECASE,
            )

            logger.info(
                "Команда STT скорректирована: %r -> %r",
                clean,
                corrected,
            )
            return corrected

    return clean


@dataclass(slots=True)
class TranscriptionAttempt:
    success: bool
    text: str = ""
    error: str = ""
    status_code: int | None = None
    retryable: bool = False


class VoiceListener:
    def __init__(
        self,
        input_device: int | str | None = None,
    ) -> None:
        logger.info("Инициализация захвата звука.")

        self.sample_rate = 16000
        self.block_size = 1024

        # Короткая естественная пауза не должна обрывать команду пополам.
        self.silence_duration = 1.5

        # Очень короткий всплеск чаще является щелчком/эхом и провоцирует
        # Whisper на выдуманные подписи вроде «тревожная музыка».
        self.minimum_speech_duration = 0.32

        # Одна запись не может продолжаться дольше 60 секунд.
        self.maximum_recording_duration = 60.0

        # До начала речи сохраняем 0,8 секунды звука.
        self.pre_roll_duration = 0.8

        self.input_device = input_device
        self.energy_threshold: float | None = None
        self.noise_floor: float = 0.0

        self._preferred_key_index = 0
        self._key_cooldowns: dict[int, float] = {}

        if not GROQ_API_KEYS:
            logger.warning(
                "Groq API-ключи отсутствуют. "
                "Запись будет работать, но транскрипция недоступна."
            )
        self.local_stt = LocalSTTFallback()
        self.last_error: str | None = None

        self._log_audio_device()

    def _log_audio_device(self) -> None:
        try:
            if self.input_device is None:
                default_input = sd.default.device[0]
                device_info = sd.query_devices(
                    default_input,
                    "input",
                )
                logger.info(
                    "Используется микрофон: index=%s, name=%s, "
                    "channels=%s, default_samplerate=%s",
                    default_input,
                    device_info.get("name"),
                    device_info.get("max_input_channels"),
                    device_info.get("default_samplerate"),
                )
            else:
                device_info = sd.query_devices(
                    self.input_device,
                    "input",
                )
                logger.info(
                    "Используется выбранный микрофон: %s",
                    device_info.get("name"),
                )
        except Exception:
            logger.exception(
                "Не удалось определить аудиоустройство."
            )

    @staticmethod
    def list_input_devices() -> list[dict]:
        devices: list[dict] = []

        for index, device in enumerate(sd.query_devices()):
            if int(device.get("max_input_channels", 0)) <= 0:
                continue

            devices.append(
                {
                    "index": index,
                    "name": device.get("name"),
                    "channels": device.get(
                        "max_input_channels"
                    ),
                    "sample_rate": device.get(
                        "default_samplerate"
                    ),
                }
            )

        return devices

    @staticmethod
    def _get_rms(data: np.ndarray) -> float:
        samples = data.astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(np.square(samples))))

    def _calibrate(
        self,
        stream: sd.InputStream,
        should_abort: Callable[[], bool] | None,
    ) -> bool:
        # Ждём завершения воспроизведения TTS, чтобы микрофон
        # не захватил собственный голос Nova.
        from modules.audio.tts import is_tts_capture_blocked
        while is_tts_capture_blocked():
            if should_abort and should_abort():
                return False
            # Drain the live input stream instead of letting PortAudio's
            # buffer fill while Nova is speaking.
            stream.read(self.block_size)

        print(
            "\n[🎤] Калибровка фона. "
            "Пожалуйста, не говорите одну секунду..."
        )


        rms_values: list[float] = []
        calibration_blocks = max(
            1,
            int(self.sample_rate / self.block_size),
        )

        for _ in range(calibration_blocks):
            if should_abort and should_abort():
                return False

            data, overflowed = stream.read(self.block_size)

            if overflowed:
                logger.warning(
                    "Переполнение аудиобуфера во время калибровки."
                )

            rms_values.append(self._get_rms(data))

        self.noise_floor = float(
            np.percentile(rms_values, 75)
        )

        # Порог адаптируется к фону, но не становится чрезмерно высоким.
        self.energy_threshold = max(
        0.006,
        min(0.045, self.noise_floor * 1.45 + 0.0015),
)


        print(
            "[🎤] Калибровка завершена. "
            f"Шум: {self.noise_floor:.4f}; "
            f"порог речи: {self.energy_threshold:.4f}"
        )

        return True

    def _update_noise_floor(self, rms: float) -> None:
        """
        Медленно адаптирует фон, только пока пользователь не говорит.
        """
        self.noise_floor = (
            self.noise_floor * 0.995
            + rms * 0.005
        )

        adaptive_threshold = (
            self.noise_floor * 1.45 + 0.0015
        )

        self.energy_threshold = max(
            0.006,
            min(0.045, adaptive_threshold),
        )



    def _record(
        self,
        should_abort: Callable[[], bool] | None,
    ) -> np.ndarray | None:
        stream_kwargs = {
            "samplerate": self.sample_rate,
            "channels": 1,
            "blocksize": self.block_size,
            "dtype": "int16",
        }

        if self.input_device is not None:
            stream_kwargs["device"] = self.input_device

        # Lazy import для избежания циклических зависимостей.
        from modules.audio.tts import is_tts_capture_blocked

        with sd.InputStream(**stream_kwargs) as stream:
            if self.energy_threshold is None:
                calibrated = self._calibrate(
                    stream,
                    should_abort,
                )

                if not calibrated:
                    return None

            assert self.energy_threshold is not None

            print(
                "[🎤] Слушаю "
                f"(порог RMS VAD: {self.energy_threshold:.4f})..."
            )

            pre_roll_blocks = max(
                1,
                int(
                    self.pre_roll_duration
                    * self.sample_rate
                    / self.block_size
                ),
            )

            silence_limit_blocks = max(
                1,
                int(
                    self.silence_duration
                    * self.sample_rate
                    / self.block_size
                ),
            )

            maximum_blocks = max(
                1,
                int(
                    self.maximum_recording_duration
                    * self.sample_rate
                    / self.block_size
                ),
            )

            minimum_active_blocks = max(
                1,
                int(
                    self.minimum_speech_duration
                    * self.sample_rate
                    / self.block_size
                ),
            )

            pre_roll: list[np.ndarray] = []
            audio_buffer: list[np.ndarray] = []

            started_speaking = False
            silence_blocks = 0
            active_blocks = 0
            peak_rms = 0.0

            while True:
                if should_abort and should_abort():
                    logger.debug(
                        "Запись отменена внешним сигналом."
                    )
                    return None

                data, overflowed = stream.read(
                    self.block_size
                )

                if overflowed:
                    logger.warning(
                        "Переполнение входного аудиобуфера."
                    )

                # Пропускаем блоки, пока TTS воспроизводит аудио,
                # чтобы избежать обратной связи микрофона.
                if is_tts_capture_blocked():
                    pre_roll.clear()
                    if started_speaking:
                        logger.info("Запись отменена: началось воспроизведение TTS.")
                        return None
                    continue

                rms = self._get_rms(data)
                peak_rms = max(peak_rms, rms)

                if not started_speaking:
                    pre_roll.append(data.copy())

                    if len(pre_roll) > pre_roll_blocks:
                        pre_roll.pop(0)

                    self._update_noise_floor(rms)

                # Для продолжения речи используем немного меньший порог.
                start_threshold = self.energy_threshold
                continue_threshold = (
                    self.energy_threshold * 0.65
                )

                is_voice = (
                    rms > (
                        continue_threshold
                        if started_speaking
                        else start_threshold
                    )
                )

                if is_voice:
                    if not started_speaking:
                        started_speaking = True
                        audio_buffer.extend(pre_roll)
                        logger.info(
                            "VAD обнаружил начало речи: "
                            "rms=%.4f threshold=%.4f",
                            rms,
                            self.energy_threshold,
                        )

                    active_blocks += 1
                    silence_blocks = 0
                    audio_buffer.append(data.copy())

                elif started_speaking:
                    silence_blocks += 1
                    audio_buffer.append(data.copy())

                    if silence_blocks >= silence_limit_blocks:
                        break

                if (
                    started_speaking
                    and len(audio_buffer) >= maximum_blocks
                ):
                    logger.info(
                        "Достигнут лимит записи 60 секунд."
                    )
                    break

            logger.info(
                "Запись завершена: active_blocks=%s, "
                "minimum=%s, peak_rms=%.4f, threshold=%.4f, "
                "total_blocks=%s",
                active_blocks,
                minimum_active_blocks,
                peak_rms,
                self.energy_threshold,
                len(audio_buffer),
            )

            if active_blocks < minimum_active_blocks:
                logger.warning(
                    "Речь отклонена как слишком короткая: "
                    "active_blocks=%s, minimum=%s, peak=%.4f",
                    active_blocks,
                    minimum_active_blocks,
                    peak_rms,
                )
                return None

            if not audio_buffer:
                return None

            return np.concatenate(
                audio_buffer,
                axis=0,
            )

    def _ordered_key_indices(self) -> list[int]:
        if not GROQ_API_KEYS:
            return []

        count = len(GROQ_API_KEYS)
        preferred = self._preferred_key_index % count

        return list(range(preferred, count)) + list(
            range(0, preferred)
        )

    def _transcribe_with_key(
        self,
        wav_path: Path,
        key_index: int,
    ) -> TranscriptionAttempt:
        api_key = GROQ_API_KEYS[key_index]

        try:
            with wav_path.open("rb") as audio_file:
                response = requests.post(
                    (
                        "https://api.groq.com/openai/v1/"
                        "audio/transcriptions"
                    ),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                    },
                    files={
                        "file": (
                            "nova_microphone.wav",
                            audio_file,
                            "audio/wav",
                        ),
                    },
                    data={
                        "model": "whisper-large-v3-turbo",
                        "language": "ru",
                        "temperature": "0",
                        "prompt": (
                            "Голосовые команды ассистенту Nova на русском языке. "
                            "Частые команды: включи, выключи, открой, закрой, "
                            "запусти, напиши, вставь, сохрани, сверни. "
                            "Приложения: Obsidian, Discord, Telegram, Chrome, "
                            "Visual Studio Code, блокнот, калькулятор, проводник."
                        ),
                    },

                    timeout=(10.0, 90.0),
                )

        except requests.Timeout as exc:
            return TranscriptionAttempt(
                success=False,
                error=f"Таймаут Groq STT: {exc}",
                retryable=True,
            )
        except requests.RequestException as exc:
            return TranscriptionAttempt(
                success=False,
                error=f"Ошибка соединения Groq STT: {exc}",
                retryable=True,
            )

        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                return TranscriptionAttempt(
                    success=False,
                    error=(
                        "Groq STT вернул поврежденный JSON: "
                        f"{exc}"
                    ),
                    status_code=200,
                    retryable=True,
                )

            text = str(payload.get("text") or "").strip()

            return TranscriptionAttempt(
                success=True,
                text=text,
                status_code=200,
            )

        response_text = response.text[:1000]

        return TranscriptionAttempt(
            success=False,
            error=(
                f"Groq STT вернул HTTP {response.status_code}: "
                f"{response_text}"
            ),
            status_code=response.status_code,
            retryable=response.status_code in {
                408,
                413,
                429,
                500,
                502,
                503,
                504,
            },
        )

    def _transcribe(
        self,
        wav_path: Path,
    ) -> str:
        if not GROQ_API_KEYS:
            logger.warning(
            "Облачный STT недоступен. "
            "Пробую локальный fallback."
        )

            return self._transcribe_local(
            wav_path
        )


        now = time.monotonic()
        attempted_keys = 0

        for key_index in self._ordered_key_indices():
            cooldown_until = self._key_cooldowns.get(
                key_index,
                0.0,
            )

            if now < cooldown_until:
                logger.info(
                    "STT Groq key %s находится на cooldown %.0f сек.",
                    key_index + 1,
                    cooldown_until - now,
                )
                continue

            attempted_keys += 1

            logger.info(
                "Отправка записи в Groq STT через key %s.",
                key_index + 1,
            )

            result = self._transcribe_with_key(
                wav_path,
                key_index,
            )

            if result.success:
                self._preferred_key_index = key_index
                return result.text

            logger.error(result.error)

            if result.status_code in {401, 403}:
                # Неверный ключ исключаем до перезапуска.
                self._key_cooldowns[key_index] = (
                    time.monotonic() + 24 * 60 * 60
                )
                continue

            if result.status_code == 429:
                self._key_cooldowns[key_index] = (
                    time.monotonic() + 90
                )
                continue

            if result.retryable:
                self._key_cooldowns[key_index] = (
                    time.monotonic() + 15
                )
                continue

            # Неповторяемая ошибка запроса обычно относится к самому
            # аудиофайлу, поэтому другой ключ не поможет.
            break

        if attempted_keys == 0:
            logger.error(
                "Все Groq STT-ключи находятся на cooldown."
            )

        return ""
    def _transcribe_local(
        self,
        wav_path: Path,
    ) -> str:
        """
        Синхронный bridge для локального async STT.

        VoiceListener.listen() уже выполняется через asyncio.to_thread,
        поэтому внутри этого рабочего потока можно создать отдельный
        event loop через asyncio.run().
        """
        if not self.local_stt.available:
            logger.info(
                "Локальный STT fallback не настроен."
            )
            return ""

        try:
            result = asyncio.run(
                self.local_stt.transcribe(
                    wav_path
                )
            )
        except Exception:
            logger.exception(
                "Ошибка локального STT fallback."
            )
            return ""

        if not result.success:
            logger.error(
                "Локальный STT завершился ошибкой: %s",
                result.error,
            )
            return ""

        logger.info(
            "Транскрипция получена через локальный STT."
        )

        return result.text.strip()
    def transcribe_file(
        self,
        wav_path: str | Path,
    ) -> str:
        """
        Распознаёт уже существующий WAV-файл.

        Используется WakeWordRuntime после локального обнаружения
        слова «Нова».
        """
        resolved_path = Path(
            wav_path
        ).resolve()

        if not resolved_path.is_file():
            logger.error(
                "STT-файл не найден: %s",
                resolved_path,
            )
            return ""

        text = self._transcribe(
            resolved_path
        )

        if not text:
            logger.warning(
                "STT не вернул текст для %s.",
                resolved_path,
            )
            return ""

        text = normalize_voice_command(
            text
        )

        if is_likely_whisper_hallucination(text):
            logger.info(
                "Отсечена галлюцинация Whisper: %r",
                text,
            )
            return ""

        print(
            f"[Вы сказали]: {text}"
        )

        return text

    def listen(
        self,
        should_abort: Callable[[], bool] | None = None,
    ) -> str:
        self.last_error = None
        try:
            audio = self._record(should_abort)
        except sd.PortAudioError as exc:
            self.last_error = f"Нет доступа к микрофону: {exc}"
            logger.exception(
                "Ошибка доступа к микрофону: %s",
                exc,
            )
            time.sleep(1.0)
            return ""
        except Exception:
            self.last_error = "Непредвиденная ошибка записи звука."
            logger.exception(
                "Непредвиденная ошибка записи звука."
            )
            time.sleep(0.5)
            return ""

        if audio is None or audio.size == 0:
            return ""

        temp_directory = Path("data/temp")
        temp_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path: Path | None = None

        try:
            file_descriptor, raw_path = tempfile.mkstemp(
                prefix="nova_mic_",
                suffix=".wav",
                dir=str(temp_directory),
            )
            os.close(file_descriptor)
            temporary_path = Path(raw_path)

            with wave.open(
                str(temporary_path),
                "wb",
            ) as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio.tobytes())

            duration_seconds = (
                len(audio) / self.sample_rate
            )

            logger.info(
                "Аудиофайл подготовлен: duration=%.2f sec, "
                "samples=%s, path=%s",
                duration_seconds,
                len(audio),
                temporary_path,
            )

            if should_abort and should_abort():
                return ""

            text = self._transcribe(temporary_path)

            if not text:
                logger.warning(
                    "STT не вернул распознанный текст."
                )
                return ""

            text = normalize_voice_command(text)
            if is_likely_whisper_hallucination(text):
                logger.info(
                    "Отсечена галлюцинация Whisper: %r",
                    text,
                )
                return ""

            print(f"[Вы сказали]: {text}")
            return text

        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(
                        missing_ok=True
                    )
                except OSError:
                    logger.warning(
                        "Не удалось удалить временную запись %s.",
                        temporary_path,
                    )
