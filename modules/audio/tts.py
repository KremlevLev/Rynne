# modules/audio/tts.py
import os
import logging
import threading
import sounddevice as sd
import re
import asyncio
import torch
from modules.ui.overlay import update_status
logger = logging.getLogger("TTS")

# ---------------------------------------------------------------------------
# Флаг воспроизведения TTS — используется VoiceListener (STT) для
# приостановки записи, пока Nova говорит, чтобы избежать обратной связи
# (микрофон не должен записывать собственный голос).
# ---------------------------------------------------------------------------
_tts_playing = False
_tts_playing_lock = threading.Lock()


def is_tts_playing() -> bool:
    """Thread-safe: воспроизводится ли сейчас аудио TTS."""
    with _tts_playing_lock:
        return _tts_playing

# Путь для хранения JIT-модели Silero v5
MODEL_PATH = "data/v5_ru.pt"
_silero_model = None
_device = torch.device('cpu')

def _get_silero_engine():
    """Ленивая инициализация Silero TTS v5 на CPU"""
    global _silero_model
    if _silero_model is None:
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        
        # Автоматическое скачивание модели при первом запуске
        if not os.path.exists(MODEL_PATH):
            logger.info("Файл модели Silero v5 не найден. Начинаю загрузку с официального сервера...")
            try:
                torch.hub.download_url_to_file('https://models.silero.ai/models/tts/ru/v5_ru.pt', MODEL_PATH)
                logger.info("Модель Silero v5 успешно загружена на диск.")
            except Exception as e:
                logger.error(f"Не удалось скачать модель Silero v5: {e}")
                return None
                
        try:
            logger.info("Загрузка Silero v5 в оперативную память...")
            torch.set_num_threads(4)  # Ограничение потоков для предотвращения перегрузки CPU
            _silero_model = torch.package.PackageImporter(MODEL_PATH).load_pickle("tts_models", "model")
            _silero_model.to(_device)
            logger.info("Модель Silero v5 готова к синтезу речи.")
        except Exception as e:
            logger.error(f"Ошибка при инициализации Silero v5: {e}")
    return _silero_model

def speak(text: str, speaker: str = "baya"):
    """Синтезирует и озвучивает текст через Silero v5 напрямую в ОЗУ с поддержкой прерывания"""
    if not text:
        return
        
    cleaned_text = text.strip()
    
    # ЗАЩИТА ОТ ОШИБОК СИНТЕЗА:
    # Проверяем, содержит ли строка хотя бы одну букву (русскую или английскую).
    # Если букв нет (например, пришли только кавычки, точки, скобки или пробелы), пропускаем.
    if not any(char.isalpha() for char in cleaned_text):
        logger.debug(f"Пропуск озвучки строки без букв: '{cleaned_text}'")
        return
        
    # ФАЗА 1: Прерываемся перед началом работы, если флаг затыкания уже установлен
    if _speech_interrupted:
        logger.debug("Воспроизведение отменено: зафиксирован флаг прерывания речи.")
        return
    
    from modules.ui.overlay import update_status
    update_status("ГОВОРИТ")

    # Печатаем реплику только если она действительно будет озвучена
    print(f"\n[🔊 Nova Говорит]: {cleaned_text}")
    phonetic_text = convert_english_to_russian_phonetic(cleaned_text)
    model = _get_silero_engine()
    if not model:
        logger.error("Голосовой движок Silero не запущен.")
        return
        
    try:
        sample_rate = 24000  # 24 кГц
        
        # ФАЗА 2: Проверка непосредственно перед тяжелым синтезом нейросети
        if _speech_interrupted:
            return
            
        # Генерация аудио
        audio = model.apply_tts(
            text=phonetic_text,
            speaker=speaker,
            sample_rate=sample_rate,
            put_accent=True,      # Автоматическое расставление ударений
            put_yo=True           # Автоматическая замена 'е' на 'ё'
        )
        
        # ФАЗА 3: Проверка перед самой отправкой аудио на звуковую карту
        if _speech_interrupted:
            return
            
        audio_data = audio.numpy()
        global _tts_playing
        # Флаг сообщает VoiceListener (STT), что сейчас играет TTS,
        # чтобы микрофон не захватывал собственный голос Nova.
        with _tts_playing_lock:
            _tts_playing = True
        try:
            sd.play(audio_data, sample_rate)
            sd.wait()  # При вызове sd.stop() в другом потоке этот метод мгновенно разблокируется
        finally:
            with _tts_playing_lock:
                _tts_playing = False
        
    except Exception as e:
        logger.error(f"Ошибка во время синтеза или воспроизведения Silero: {e}")



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
    print("\n[🔇 Nova]: Воспроизведение прервано.")
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