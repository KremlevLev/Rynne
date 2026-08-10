# modules/audio/tts.py
import os
import logging
import threading
import time
import sounddevice as sd
import re
import asyncio
import io
import html
import json
import wave
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import requests
from modules.ui.overlay import update_status
logger = logging.getLogger("TTS")

# ---------------------------------------------------------------------------
# Флаг воспроизведения TTS — используется VoiceListener (STT) для
# приостановки записи, пока Nova говорит, чтобы избежать обратной связи
# (микрофон не должен записывать собственный голос).
# ---------------------------------------------------------------------------
_tts_playing = False
_tts_playing_lock = threading.Lock()
_tts_output_lock = threading.Lock()
_tts_last_finished_at = float("-inf")


SILERO_VOICES = (
    {"id": "aidar", "name": "Aidar", "gender": "male"},
    {"id": "baya", "name": "Baya", "gender": "female"},
    {"id": "kseniya", "name": "Kseniya", "gender": "female"},
    {"id": "xenia", "name": "Xenia", "gender": "female"},
    {"id": "eugene", "name": "Eugene", "gender": "male"},
)
GROQ_ORPHEUS_VOICES = (
    {"id": "autumn", "name": "Autumn", "gender": "female"},
    {"id": "diana", "name": "Diana", "gender": "female"},
    {"id": "hannah", "name": "Hannah", "gender": "female"},
    {"id": "austin", "name": "Austin", "gender": "male"},
    {"id": "daniel", "name": "Daniel", "gender": "male"},
    {"id": "troy", "name": "Troy", "gender": "male"},
)
TTS_STYLES = ("neutral", "warm", "cheerful", "professional", "confident")
TTS_SETTINGS_PATH = Path(
    os.getenv("NOVA_TTS_SETTINGS_PATH", "data/tts-settings.json")
)
_tts_settings_lock = threading.RLock()


@dataclass(frozen=True, slots=True)
class TTSSettings:
    language: str = "auto"
    ru_voice: str = "baya"
    en_voice: str = "autumn"
    speed: float = 1.0
    style: str = "neutral"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _validated_tts_settings(settings: TTSSettings) -> TTSSettings:
    language = str(settings.language).strip().lower()
    if language not in {"auto", "ru", "en"}:
        raise ValueError("TTS language must be auto, ru or en.")
    ru_voices = {voice["id"] for voice in SILERO_VOICES}
    en_voices = {voice["id"] for voice in GROQ_ORPHEUS_VOICES}
    ru_voice = str(settings.ru_voice).strip().lower()
    en_voice = str(settings.en_voice).strip().lower()
    if ru_voice not in ru_voices:
        raise ValueError("Unknown Silero voice.")
    if en_voice not in en_voices:
        raise ValueError("Unknown Groq Orpheus voice.")
    speed = float(settings.speed)
    if not 0.7 <= speed <= 1.6:
        raise ValueError("TTS speed must be between 0.7 and 1.6.")
    style = str(settings.style).strip().lower()
    if style not in TTS_STYLES:
        raise ValueError("Unknown TTS speaking style.")
    return replace(
        settings,
        language=language,
        ru_voice=ru_voice,
        en_voice=en_voice,
        speed=speed,
        style=style,
    )


def _load_tts_settings() -> TTSSettings:
    try:
        raw = json.loads(TTS_SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("TTS settings must be an object.")
        return _validated_tts_settings(TTSSettings(
            language=str(raw.get("language", "auto")),
            ru_voice=str(raw.get("ru_voice", "baya")),
            en_voice=str(raw.get("en_voice", "autumn")),
            speed=float(raw.get("speed", 1.0)),
            style=str(raw.get("style", "neutral")),
        ))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return TTSSettings()


_tts_settings = _load_tts_settings()


def get_tts_settings() -> TTSSettings:
    with _tts_settings_lock:
        return replace(_tts_settings)


def update_tts_settings(**changes: object) -> TTSSettings:
    global _tts_settings
    allowed = {"language", "ru_voice", "en_voice", "speed", "style"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Unknown TTS settings: {', '.join(sorted(unknown))}")
    with _tts_settings_lock:
        candidate = replace(_tts_settings, **changes)
        candidate = _validated_tts_settings(candidate)
        TTS_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = TTS_SETTINGS_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(candidate.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(TTS_SETTINGS_PATH)
        _tts_settings = candidate
        return replace(candidate)


def get_tts_catalog() -> dict[str, object]:
    try:
        from core.config import GROQ_API_KEYS
        groq_available = bool(GROQ_API_KEYS)
    except Exception:
        groq_available = False
    return {
        "languages": ["auto", "ru", "en"],
        "styles": list(TTS_STYLES),
        "voices": [
            *(
                {
                    **voice,
                    "language": "ru",
                    "engine": "silero",
                    "model": "v5_ru",
                    "online": False,
                    "available": True,
                }
                for voice in SILERO_VOICES
            ),
            *(
                {
                    **voice,
                    "language": "en",
                    "engine": "groq",
                    "model": "canopylabs/orpheus-v1-english",
                    "online": True,
                    "available": groq_available,
                }
                for voice in GROQ_ORPHEUS_VOICES
            ),
        ],
        "speed": {"min": 0.7, "max": 1.6, "step": 0.05},
    }


def is_tts_playing() -> bool:
    """Thread-safe: воспроизводится ли сейчас аудио TTS."""
    with _tts_playing_lock:
        return _tts_playing


def is_tts_capture_blocked(cooldown_seconds: float = 1.0) -> bool:
    """Keep STT/wake detection closed while speakers and echo tail are audible."""
    with _tts_playing_lock:
        return _tts_playing or (
            time.monotonic() - _tts_last_finished_at
            < max(0.0, cooldown_seconds)
        )

# Путь для хранения JIT-модели Silero v5
MODEL_PATH = "data/v5_ru.pt"
_silero_model = None
_torch_module = None
_silero_engine_lock = threading.Lock()
_silero_load_error: str | None = None
_silero_retry_after = 0.0

def _get_silero_engine():
    """Ленивая инициализация Silero TTS v5 на CPU"""
    global _silero_model, _torch_module, _silero_load_error, _silero_retry_after
    if _silero_model is not None:
        return _silero_model
    if _silero_load_error and time.monotonic() < _silero_retry_after:
        logger.error("Silero временно недоступен: %s", _silero_load_error)
        return None

    # Startup warm-up and the first reply can arrive at the same time. Torch
    # PackageImporter is not safe to initialize twice in parallel.
    with _silero_engine_lock:
        if _silero_model is not None:
            return _silero_model
        if _silero_load_error and time.monotonic() < _silero_retry_after:
            return None
        started_at = time.monotonic()
        if _torch_module is None:
            logger.info("Загрузка локального TTS runtime...")
            import torch

            _torch_module = torch

        torch = _torch_module
        device = torch.device("cpu")
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        
        # Автоматическое скачивание модели при первом запуске
        if not os.path.exists(MODEL_PATH):
            logger.info("Файл модели Silero v5 не найден. Начинаю загрузку с официального сервера...")
            try:
                torch.hub.download_url_to_file('https://models.silero.ai/models/tts/ru/v5_ru.pt', MODEL_PATH)
                logger.info("Модель Silero v5 успешно загружена на диск.")
            except Exception as e:
                logger.error(f"Не удалось скачать модель Silero v5: {e}")
                _silero_load_error = str(e)
                _silero_retry_after = time.monotonic() + 60.0
                return None
                
        try:
            logger.info("Загрузка Silero v5 в оперативную память...")
            torch.set_num_threads(2)
            try:
                torch.set_num_interop_threads(1)
            except RuntimeError:
                # PyTorch разрешает менять interop pool только до первой
                # параллельной операции; повторный warm-up не должен падать.
                pass
            _silero_model = torch.package.PackageImporter(MODEL_PATH).load_pickle("tts_models", "model")
            _silero_model.to(device)
            _silero_load_error = None
            _silero_retry_after = 0.0
            logger.info(
                "Модель Silero v5 готова к синтезу речи за %.1f сек.",
                time.monotonic() - started_at,
            )
        except Exception as e:
            logger.error(f"Ошибка при инициализации Silero v5: {e}")
            _silero_model = None
            _silero_load_error = str(e)
            _silero_retry_after = time.monotonic() + 60.0
    return _silero_model

def warm_up_tts() -> bool:
    """Load the local model before the first assistant reply."""
    return _get_silero_engine() is not None


def _detect_tts_language(text: str) -> str:
    cyrillic = sum("а" <= char.lower() <= "я" or char.lower() == "ё" for char in text)
    latin = sum("a" <= char.lower() <= "z" for char in text)
    return "ru" if cyrillic >= latin else "en"


def _silero_prosody_rate(speed: float) -> str | None:
    """Map the shared UI scale to Silero's native SSML rate presets."""
    if speed <= 0.76:
        return "x-slow"
    if speed <= 0.92:
        return "slow"
    if speed < 1.12:
        return None
    if speed < 1.42:
        return "fast"
    return "x-fast"


def _play_audio(audio: np.ndarray, sample_rate: int) -> bool:
    global _tts_playing, _tts_last_finished_at
    with _tts_output_lock:
        with _tts_playing_lock:
            _tts_playing = True
        try:
            sd.play(audio, sample_rate)
            sd.wait()
        finally:
            with _tts_playing_lock:
                _tts_playing = False
                _tts_last_finished_at = time.monotonic()
    return True


def _groq_keys() -> tuple[str, ...]:
    try:
        from core.config import GROQ_API_KEYS
        return tuple(GROQ_API_KEYS)
    except Exception:
        return ()


def _speak_groq(text: str, *, voice: str, speed: float, style: str) -> bool:
    keys = _groq_keys()
    if not keys:
        raise RuntimeError("Groq API key is required for English TTS.")
    spoken_text = text if style == "neutral" else f"[{style}] {text}"
    last_error = "Groq TTS request failed."
    for api_key in keys:
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "canopylabs/orpheus-v1-english",
                    "input": spoken_text,
                    "voice": voice,
                    "response_format": "wav",
                    "sample_rate": 24000,
                    "speed": speed,
                },
                timeout=35,
            )
            if response.status_code >= 400:
                last_error = f"Groq TTS returned HTTP {response.status_code}."
                continue
            with wave.open(io.BytesIO(response.content), "rb") as audio_file:
                channels = audio_file.getnchannels()
                sample_width = audio_file.getsampwidth()
                sample_rate = audio_file.getframerate()
                frames = audio_file.readframes(audio_file.getnframes())
            if sample_width != 2:
                raise RuntimeError("Groq returned an unsupported WAV sample width.")
            audio = np.frombuffer(frames, dtype=np.int16)
            if channels > 1:
                audio = audio.reshape(-1, channels)
            return _play_audio(audio, sample_rate)
        except (OSError, ValueError, requests.RequestException) as exc:
            last_error = f"Groq TTS failed: {exc}"
    raise RuntimeError(last_error)


def speak(
    text: str,
    speaker: str | None = None,
    *,
    language: str | None = None,
    speed: float | None = None,
    style: str | None = None,
) -> bool:
    """Синтезирует и озвучивает текст через Silero v5 напрямую в ОЗУ с поддержкой прерывания"""
    if not text:
        return False
        
    cleaned_text = text.strip()
    
    # ЗАЩИТА ОТ ОШИБОК СИНТЕЗА:
    # Проверяем, содержит ли строка хотя бы одну букву (русскую или английскую).
    # Если букв нет (например, пришли только кавычки, точки, скобки или пробелы), пропускаем.
    if not any(char.isalpha() for char in cleaned_text):
        logger.debug(f"Пропуск озвучки строки без букв: '{cleaned_text}'")
        return False
        
    # ФАЗА 1: Прерываемся перед началом работы, если флаг затыкания уже установлен
    if _speech_interrupted:
        logger.debug("Воспроизведение отменено: зафиксирован флаг прерывания речи.")
        return False
    
    from modules.ui.overlay import update_status
    update_status("ГОВОРИТ")

    # Печатаем реплику только если она действительно будет озвучена
    print(f"\n[🔊 Rynne говорит]: {cleaned_text}")
    settings = get_tts_settings()
    selected_language = language or settings.language
    if selected_language == "auto":
        selected_language = _detect_tts_language(cleaned_text)
    selected_speed = float(speed if speed is not None else settings.speed)
    selected_style = style or settings.style
    if selected_language == "en":
        return _speak_groq(
            cleaned_text,
            voice=speaker or settings.en_voice,
            speed=selected_speed,
            style=selected_style,
        )

    phonetic_text = convert_english_to_russian_phonetic(cleaned_text)
    model = _get_silero_engine()
    if not model:
        logger.error("Голосовой движок Silero не запущен.")
        return False
        
    try:
        sample_rate = 24000  # 24 кГц
        
        # ФАЗА 2: Проверка непосредственно перед тяжелым синтезом нейросети
        if _speech_interrupted:
            return False
            
        # Silero changes cadence during synthesis through native SSML prosody.
        # Post-processing the finished waveform makes voices metallic, so it is
        # deliberately not used here.
        prosody_rate = _silero_prosody_rate(selected_speed)
        if prosody_rate is None:
            audio = model.apply_tts(
                text=phonetic_text,
                speaker=speaker or settings.ru_voice,
                sample_rate=sample_rate,
                put_accent=True,
                put_yo=True,
            )
        else:
            ssml_text = (
                '<speak><prosody rate="'
                f'{prosody_rate}">{html.escape(phonetic_text)}</prosody></speak>'
            )
            audio = model.apply_tts(
                ssml_text=ssml_text,
                speaker=speaker or settings.ru_voice,
                sample_rate=sample_rate,
            )
        
        # ФАЗА 3: Проверка перед самой отправкой аудио на звуковую карту
        if _speech_interrupted:
            return False
            
        return _play_audio(audio.numpy(), sample_rate)
        
    except Exception as e:
        logger.error(f"Ошибка во время синтеза или воспроизведения Silero: {e}")
        return False


def preview_tts(
    *,
    language: str,
    voice: str,
    speed: float,
    style: str = "neutral",
) -> bool:
    sample = (
        "Привет! Я Rynne. Так будет звучать мой голос."
        if language == "ru"
        else "Hello! I'm Rynne. This is how my voice will sound."
    )
    return speak(
        sample,
        speaker=voice,
        language=language,
        speed=speed,
        style=style,
    )



# --- ГОЛОСОВЫЕ ФИЛЬТРЫ И АСИНХРОННЫЙ ПЛЕЕР (ДЛЯ РАБОТЫ В СОСТАВЕ MAIN.PY) ---

def is_text_code_or_json(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return False
    if "{" in clean and "}" in clean:
        return True
    if '"name":' in clean or '"parameters":' in clean or '"function":' in clean:
        return True
    if clean.startswith("[") and clean.endswith("]"):
        return True
    return False

def is_inside_xml_block(text: str, allowed_tool_names: list[str]) -> bool:
    open_func_tags = text.count("<function=")
    close_func_tags = text.count("</function>")
    if open_func_tags > close_func_tags:
        return True
    for func_name in allowed_tool_names:
        open_count = text.count(f"<{func_name}>")
        close_count = text.count(f"</{func_name}>")
        if open_count > close_count:
            return True
    last_bracket = text.rfind("<")
    if last_bracket > text.rfind(">"):
        return True
    return False

def clean_text_for_speech(text: str, allowed_tool_names: list[str]) -> str:
    cleaned = text
    cleaned = re.sub(
    r"<function=\w+>.*?</function>",
    "",
    cleaned,
    flags=re.DOTALL,
    )


    for func_name in allowed_tool_names:
        pattern = re.compile(rf'<{func_name}>.*?</{func_name}>', re.DOTALL)
        cleaned = pattern.sub('', cleaned)
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

async def speak_worker(queue: asyncio.Queue):
    while True:
        sentence = await queue.get()
        if sentence is None:
            queue.task_done()
            break
        try:
            # Если прилетел сигнал стоп — очищаем очередь и выходим
            if _speech_interrupted:
                while not queue.empty():
                    try:
                        queue.get_nowait()
                        queue.task_done()  # Подтверждаем сброс фоновых элементов
                    except asyncio.QueueEmpty:
                        break
                # Текущий элемент подтвердится автоматически в блоке finally при выходе
                break
                
            await asyncio.to_thread(speak, sentence)
        except Exception as e:
            logger.error(f"Ошибка TTS воркера: {e}")
        finally:
            queue.task_done()  # Вызывается ровно один раз для извлеченного элемента

_speech_interrupted = False

def stop_speaking():
    """Моментально останавливает текущее воспроизведение и взводит флаг прерывания"""
    global _speech_interrupted
    _speech_interrupted = True
    try:
        sd.stop()  # Win32-метод sounddevice мгновенно обрывает поток в динамиках
    except Exception:
        pass
    print("\n[🔇 Rynne]: Воспроизведение прервано.")
    update_status("СЛУШАЕТ")

def is_interrupted() -> bool:
    return _speech_interrupted

def reset_interrupt_flag():
    global _speech_interrupted
    _speech_interrupted = False

# === БЛОК ЕСТЕСТВЕННОЙ РУССКОЙ ТРАНСКРИПЦИИ АНГЛИЙСКИХ СЛОВ ===

# Словарь идеального произношения частых технических терминов
TECH_GLOSSARY = {
    "llm": "эл эл эм",
    "jax": "джакс",
    "ollama": "оллама",
    "singularity": "сингулярити",
    "cluster": "кластер",
    "instruction": "инстракшн",
    "python": "пайтон",
    "vs code": "вэ эс код",
    "vscode": "вэ эс код",
    "chrome": "хром",
    "obsidian": "обсидиан",
    "discord": "дискорд",
    "telegram": "телеграм",
    "spotify": "спотифай",
    "explorer": "эксплорер",
    "notepad": "ноутпад",
    "calculator": "калькулятор",
    "y_true": "игрек тру",
    "y_pred": "игрек пред",
    "precision": "пресижн",
    "recall": "рикол",
    "f1": "эф один",
    "true": "тру",
    "pred": "пред",
    "git": "гит",
    "github": "гитхаб",
    "api": "апи",
    "json": "джейсон",
    "xml": "икс эм эль",
    "windows": "виндовс",
    "os": "о эс",
    "cpu": "цэпэу",
    "ram": "память",
    "gpu": "гэпэу",
    "cmd": "командная строка",
    "terminal": "терминал",
    "main": "мейн",
    "test": "тест",
    "py": "пай",
    "y": "игрек",
    "x": "икс",
    "metrics": "метрикс",
    ".": "точка",
    ",": "запятая",
    "kubernetes": "кубернетс",
    "docker": "докер",
    "tensorflow": "тэнсорфлоу",
    "executor": "экзекутор",
    "pycache": "пайкэш",
    "init":"инит",
    "overlay":"оверлэй",
    "gitignore":"гитигнор", 
    "md":"эмдэ",
    "txt":"тииксти",
    "ctrl": "контрл",
    "shift": "шифт",
    "space": "cпэйс"
}

def transliterate_word(word: str) -> str:
    """Преобразует одно латинское слово в естественное русское написание для Silero"""
    w = word.lower().strip()
    
    # 1. Проверяем точный словарь технических терминов
    if w in TECH_GLOSSARY:
        return TECH_GLOSSARY[w]
        
    # 2. Обрабатываем переменные с нижним подчеркиванием (например, y_true)
    if "_" in w:
        parts = w.split("_")
        return " ".join(transliterate_word(p) for p in parts if p)
        
    # 3. Разделяем CamelCase (например, CalculateMetrics -> calculate metrics)
    w_camel = re.sub(r'([a-z])([A-Z])', r'\1 \2', word)
    if " " in w_camel:
        return " ".join(transliterate_word(p) for p in w_camel.split() if p)

    w = w_camel.lower()

    # 4. Если это одиночная буква
    if len(w) == 1:
        single_letters = {
            'a': 'а', 'b': 'би', 'c': 'си', 'd': 'ди', 'e': 'и', 'f': 'эф', 'g': 'джи', 'h': 'эйч',
            'i': 'ай', 'j': 'джей', 'k': 'кей', 'l': 'эл', 'm': 'эм', 'n': 'эн', 'o': 'о', 'p': 'пи',
            'q': 'кью', 'r': 'ар', 's': 'эс', 't': 'ти', 'u': 'ю', 'v': 'ви', 'w': 'дабл ю', 'x': 'икс',
            'y': 'игрек', 'z': 'зет'
        }
        return single_letters.get(w, w)

    # 5. Если слово заканчивается на цифры (например, f1, g2)
    match = re.match(r'^([a-zA-Z]+)([0-9]+)$', w)
    if match:
        letters, digits = match.groups()
        digit_names = {"0": "ноль", "1": "один", "2": "два", "3": "три", "4": "четыре", "5": "пять", "6": "шесть", "7": "семь", "8": "восемь", "9": "девять"}
        digit_str = " " + " ".join(digit_names.get(d, d) for d in digits)
        return transliterate_word(letters) + digit_str

    # 6. Если слово начинается с цифр (например, 32B)
    match_rev = re.match(r'^([0-9]+)([a-zA-Z]+)$', w)
    if match_rev:
        digits, letters = match_rev.groups()
        return digits + " " + transliterate_word(letters)

    # 7. Правила открытого английского слога (silent 'e' на конце)
    w = re.sub(r'ate\b', 'ейт', w)
    w = re.sub(r'ite\b', 'айт', w)
    w = re.sub(r'ike\b', 'айк', w)
    w = re.sub(r'ime\b', 'айм', w)
    w = re.sub(r'ine\b', 'айн', w)
    w = re.sub(r'ive\b', 'айв', w)
    w = re.sub(r'ube\b', 'ьюб', w)
    w = re.sub(r'one\b', 'оун', w)
    w = re.sub(r'use\b', 'ьюз', w)

    # 8. Базовые правила чтения сложных буквосочетаний (диграфы)
    w = re.sub(r'tion\b', 'шн', w)
    w = re.sub(r'tions\b', 'шнс', w)
    w = re.sub(r'ing\b', 'инг', w)
    w = re.sub(r'oo', 'у', w)
    w = re.sub(r'ee', 'и', w)
    w = re.sub(r'ea', 'и', w)
    w = re.sub(r'ai', 'ей', w)
    w = re.sub(r'ay', 'ей', w)
    w = re.sub(r'ey', 'ей', w)
    w = re.sub(r'oy', 'ой', w)
    w = re.sub(r'sh', 'ш', w)
    w = re.sub(r'ch', 'ч', w)
    w = re.sub(r'ph', 'ф', w)
    w = re.sub(r'th', 'т', w)
    w = re.sub(r'ck', 'к', w)
    w = re.sub(r'qu', 'кв', w)
    w = re.sub(r'c(?=[eiy])', 'с', w)
    w = re.sub(r'g(?=[eiy])', 'дж', w)
    w = re.sub(r'x', 'кс', w)
    w = re.sub(r'w', 'в', w)
    w = re.sub(r'h', 'х', w)
    w = re.sub(r'j', 'дж', w)
    w = re.sub(r'y', 'и', w)
    
    # 9. Посимвольный маппинг оставшихся букв в естественные русские звуки
    char_map = {
        'a': 'а', 'b': 'б', 'c': 'к', 'd': 'д', 'e': 'е', 'f': 'ф',
        'g': 'г', 'i': 'и', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н',
        'o': 'о', 'p': 'п', 'q': 'к', 'r': 'р', 's': 'с', 't': 'т',
        'u': 'у', 'v': 'в', 'z': 'з'
    }
    
    res = []
    for char in w:
        res.append(char_map.get(char, char))
    return "".join(res)

def convert_english_to_russian_phonetic(text: str) -> str:
    """Находит в тексте латинские слова, точки расширений и заменяет их на русские аналоги"""
    # Если в тексте нет латинских букв, возвращаем исходную строку
    if not any(c.isalpha() and ord(c) < 128 for c in text):
        return text

    # Предварительно обрабатываем расширения файлов, разделяя их пробелом перед разбором слов (например, main.py -> main py)
    processed_text = re.sub(r'\b([a-zA-Z0-9_]+)\.([a-zA-Z0-9]+)\b', r'\1 \2', text)

    def replace_match(match):
        token = match.group(0)
        if any(c.isalpha() and ord(c) < 128 for c in token):
            return transliterate_word(token)
        return token
        
    return re.sub(r'[a-zA-Z0-9_]+', replace_match, processed_text)
