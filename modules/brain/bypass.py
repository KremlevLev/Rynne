# modules/brain/bypass.py
import re
from modules.tools.os_utils import change_volume, close_application, get_current_time, manage_windows

LAUNCH_VERBS = [
    "запусти", "запустить", "запускай", "запускаю", "запустил",
    "открой", "открыть", "открывай", "открываю", "открыл",
    "включи", "включить", "включай", "включаю", "включил", "запуск"
]

CLOSE_VERBS = [
    "выключи", "выключить", "выключай", "выключаю", "выключил",
    "закрой", "закрыть", "закрывай", "закрываю", "закрыл",
    "прибей", "прибить", "убей", "убить", "заверши", "завершить"
]
all_verbs = (
    set(LAUNCH_VERBS)
    | set(CLOSE_VERBS)
    | {
        "сделай",
        "поставь",
        "установи",
        "сверни",
    }
)

# Быстрый Regex Bypass (время, системная громкость, окна)
FAST_COMMAND_PATTERNS = [
    (
        re.compile(
            r"\b(?:установи|сделай|поставь)?\s*"
            r"(?:громкость|звук)\s*(?:на\s+)?"
            r"(\d{1,3})\b",
            re.IGNORECASE,
        ),
        lambda match: change_volume(match.group(1)),
    ),
    (
        re.compile(
            r"\b(?:"
            r"сделай\s+(?:звук|громкость)\s+тише|"
            r"убавь\s+(?:звук|громкость)?|"
            r"потише|тише|уменьши\s+громкость"
            r")\b",
            re.IGNORECASE,
        ),
        lambda match: change_volume("down"),
    ),
    (
        re.compile(
            r"\b(?:"
            r"сделай\s+(?:звук|громкость)\s+громче|"
            r"прибавь\s+(?:звук|громкость)?|"
            r"громче|увеличь\s+громкость"
            r")\b",
            re.IGNORECASE,
        ),
        lambda match: change_volume("up"),
    ),
    (
        re.compile(
            r"\b(?:выключи звук|включи звук|муте|мьют)\b",
            re.IGNORECASE,
        ),
        lambda match: change_volume("mute"),
    ),
    (
        re.compile(
            r"\b(?:сколько времени|который час|"
            r"точное время)\b",
            re.IGNORECASE,
        ),
        lambda match: get_current_time(),
    ),
    (
        re.compile(
            r"\bсверни\s+(?:все\s+)?окна\b",
            re.IGNORECASE,
        ),
        lambda match: manage_windows("minimize_all"),
    ),
    (
        re.compile(
            r"\bзакр(?:ой|ывай|ыть)\s+"
            r"(?:активное\s+)?окно\b",
            re.IGNORECASE,
        ),
        lambda match: manage_windows("close_current"),
    ),
]


def check_instant_app_launch(user_text: str, app_launcher) -> tuple[bool, str]:
    """Мгновенно находит и запускает ярлык в обход нейросети"""
    if is_complex_request(user_text):
        return False, ""
    text_clean = user_text.lower().strip()
    for verb in LAUNCH_VERBS:
        pattern = rf'\b{verb}\s+(.+)'
        match = re.search(pattern, text_clean)
        if match:
            extracted_app_name = match.group(1).strip().rstrip(".!?")
            success, message = app_launcher.launch_by_name(extracted_app_name)
            if success:
                return True, message
    return False, ""

def check_instant_app_close(user_text: str) -> tuple[bool, str]:
    """Мгновенно находит процесс программы и завершает его локально за 5 мс"""
    if is_complex_request(user_text):
        return False, ""
    text_clean = user_text.lower().strip()
    for verb in CLOSE_VERBS:
        pattern = rf'\b{verb}\s+(.+)'
        match = re.search(pattern, text_clean)
        if match:
            extracted_app_name = match.group(1).strip().rstrip(".!?")
            message = close_application(extracted_app_name)
            if "не найдено" not in message:
                return True, message
    return False, ""

def check_fast_commands(
    user_text: str,
) -> tuple[bool, str]:
    if is_complex_request(user_text):
        return False, ""

    for pattern, action in FAST_COMMAND_PATTERNS:
        match = pattern.search(user_text)

        if match:
            actual_result = action(match)
            return True, str(actual_result)

    return False, ""


def is_complex_request(user_text: str) -> bool:
    """
    Проверяет, содержит ли фраза составные команды.
    Если да — возвращает True, заставляя систему передать управление LLM.
    """
    text = user_text.lower().strip()
    # Если в запросе есть связующие союзы или знаки препинания
    complex_markers = [",", " и потом", " а потом", " затем", " после чего", " а также"]
    if any(marker in text for marker in complex_markers):
        return True
        
    # Считаем количество глаголов действий во фразе
    all_verbs = LAUNCH_VERBS + CLOSE_VERBS + ["сделай", "поставь", "установи", "сверни", "закрой"]
    verb_count = sum(1 for verb in all_verbs if f" {verb} " in f" {text} ")
    if verb_count > 1:
        return True
        
    return False

def determine_model_by_complexity(user_text: str, has_image: bool, needs_tools: bool) -> str:
    """
    Анализирует запрос и выбирает оптимальную по соотношению скорость/интеллект модель.
    """
    from core.config import MODEL_CV_BASE, MODEL_BASIC_TOOLS, MODEL_COMPLEX_TOOLS
    
    # Уровень 1: Базовые вопросы, обычный чат или анализ экрана (CV) -> Llama 4 Scout
    if has_image or not needs_tools:
        return MODEL_CV_BASE
        
    # Уровень 3: Многоступенчатый тул-коллинг (сложные составные запросы) -> GPT OSS 120B
    if is_complex_request(user_text):
        return MODEL_COMPLEX_TOOLS
        
    # Groq использует GPT OSS 120B и для одиночного тул-коллинга:
    # слабая модель не даёт выигрыша по доступной квоте.
    return MODEL_BASIC_TOOLS
