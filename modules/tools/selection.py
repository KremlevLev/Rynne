"""Контекстный выбор небольшого, но достаточного набора инструментов."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from modules.tools.tool_visibility import filter_tools_for_model


# Точные подсказки остаются самым сильным сигналом. В отличие от старого
# селектора они дополняются группами возможностей, именами/описаниями tools и
# безопасным набором восстановления для незнакомых команд.
KEYWORDS_BY_TOOL: dict[str, set[str]] = {
    "get_current_time": {"время", "дата", "который час", "сегодня", "сейчас"},
    "get_system_status": {
        "система", "память", "оперативка", "cpu", "батарея", "загрузка",
    },
    "open_application": {"открыть", "открой", "запустить", "запусти", "включить"},
    "open_application_batch": {
        "несколько приложений", "несколько программ",
        "приложений", "программ",
    },
    "close_application": {"закрыть", "закрой", "выключить", "остановить"},
    "list_active_windows": {"список окон", "активные окна", "что запущено"},
    "manage_windows": {"свернуть", "развернуть", "закрыть окно", "окна"},
    "write_in_application": {
        "напечатать", "напечатай", "ввести", "введи", "написать", "напиши",
    },
    "search_web_tavily": {
        "найти", "найди", "поиск", "поищи", "интернет", "в сети",
    },
    "scrape_webpage": {"прочитать страницу", "страница", "сайт", "webpage"},
    "open_website": {"открыть сайт", "перейти", "open website", "url"},
    "read_text_file": {"прочитать", "прочитай", "файл", "документ", "readme"},
    "write_text_file": {"записать", "создать файл", "сохранить файл"},
    "apply_text_patch": {"исправить", "исправь", "патч", "изменить код"},
    "search_files": {"поиск файлов", "найти файл", "найди файл", "locate"},
    "save_to_memory": {"запомни", "запомнить", "записать в память"},
    "save_memory": {"запомни", "запомнить", "записать в память"},
    "search_in_memory": {"вспомни", "найти в памяти", "что помнишь"},
    "search_memory": {"вспомни", "найти в памяти", "что помнишь"},
    "browser_start": {"браузер", "browser"},
    "browser_open_url": {"открыть url", "перейти по ссылке", "открыть сайт"},
    "browser_click": {"клик", "кликни", "нажать кнопку", "нажми кнопку"},
    "browser_fill": {"заполнить", "заполни", "form", "поле"},
    "browser_screenshot": {"скриншот сайта", "снимок страницы"},
    "git_status": {"git", "статус репозитория", "git status"},
    "git_log": {"git log", "коммиты", "commits"},
    "git_branch": {"ветка", "branch"},
    "git_diff": {"изменения в коде", "diff"},
    "git_commit": {"закоммить", "commit"},
    "inspect_project": {"проект", "репозиторий", "структура", "entry point"},
    "run_terminal_command": {
        "терминал", "команда", "консоль", "powershell", "pytest", "npm",
    },
    "execute_plan": {"по шагам", "выполни план", "многошаг", "сначала"},
    "start_background_plan": {"в фоне", "фонов", "background", "асинхронно"},
}


ACTION_MARKERS = (
    "открой", "запусти", "включи", "закрой", "выключи", "напиши",
    "вставь", "введи", "напечатай", "создай", "установи", "нажми",
    "кликни", "сохрани", "перемести", "переименуй", "удали", "скопируй",
    "скачай", "загрузи", "выполни", "запомни", "напомни", "найди",
    "поищи", "прочитай", "проверь", "проанализируй", "исправь",
    "обнови", "собери", "отправь", "заполни", "сделай",
    "open ", "run ", "start ", "close ", "write ", "create ", "install ",
    "click ", "save ", "move ", "rename ", "delete ", "copy ", "download ",
    "find ", "search ", "read ", "check ", "fix ", "update ", "send ",
)


CAPABILITY_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("время", "дата", "таймер", "напомни", "напоминан", "reminder"),
        (
            "get_current_time", "set_timer", "set_reminder",
            "get_active_reminders",
        ),
    ),
    (
        (
            "приложен", "программ", "окно", "блокнот", "калькулятор",
            "obsidian", "telegram", "discord", "chrome", "vscode", "vs code",
        ),
        (
            "open_application", "open_application_batch",
            "close_application", "list_active_windows",
            "manage_windows", "write_in_application",
        ),
    ),
    (
        ("сайт", "страниц", "браузер", "url", "ссылка", "интернет", "в сети"),
        (
            "search_web_tavily", "scrape_webpage", "open_website",
            "browser_start", "browser_open_url", "browser_get_page_text",
            "browser_click", "browser_fill", "browser_screenshot",
            "browser_status", "browser_close", "browser_research",
        ),
    ),
    (
        (
            "файл", "папк", "директор", "документ", "readme", "roadmap",
            "workspace", "рабочем столе",
        ),
        (
            "search_files", "read_text_file", "write_text_file",
            "apply_text_patch", "get_file_diff", "rollback_file",
            "get_clipboard_content", "set_clipboard_content",
        ),
    ),
    (
        (
            "код", "проект", "репозитор", "ошибк", "traceback", "тест",
            "pytest", "npm", "сервер", "терминал", "команд", "скрипт",
            "python", "сборк", "рефактор",
        ),
        (
            "inspect_project", "read_text_file", "search_files",
            "apply_text_patch", "write_text_file", "get_file_diff",
            "run_terminal_command", "start_process", "get_process_status",
            "read_process_output", "stop_process", "list_processes",
            "run_project_tests", "start_development_server",
            "edit_file_transactionally",
        ),
    ),
    (
        ("git", "коммит", "commit", "ветк", "branch", "diff", "pull request"),
        (
            "git_status", "git_diff", "git_log", "git_commit", "git_branch",
            "inspect_project",
        ),
    ),
    (
        ("памят", "запомни", "вспомни", "что знаешь обо мне"),
        (
            "save_to_memory", "search_in_memory", "save_memory",
            "search_memory", "delete_memory", "clear_all_memories",
        ),
    ),
    (
        ("буфер", "clipboard", "скопируй", "вставь"),
        ("get_clipboard_content", "set_clipboard_content"),
    ),
    (
        ("артефакт", "artifact"),
        ("store_artifact", "read_artifact", "delete_artifact"),
    ),
    (
        ("громк", "звук", "музык", "видео", "медиа", "battery", "cpu", "ram"),
        ("change_volume", "manage_media", "get_system_status"),
    ),
    (
        ("в фоне", "фонов", "background", "план", "по шагам", "сначала"),
        (
            "execute_plan", "get_plan_status", "cancel_plan",
            "start_background_plan", "get_background_plan_status",
            "list_background_plans", "cancel_background_plan",
        ),
    ),
)


GUI_PRIMITIVE_MARKERS: dict[str, tuple[str, ...]] = {
    "focus_window": ("фокус", "активируй окно", "переключись на окно"),
    "press_keyboard_combination": (
        "клавиш", "горяч", "ctrl", "alt", "shift", "enter", "escape",
    ),
    "type_text": ("напечатай", "введи текст", "вставь текст"),
    "mouse_click": ("кликни", "клик", "по координат", "нажми на экране"),
}


MCP_SERVER_ALIASES: dict[str, tuple[str, ...]] = {
    "github": ("github", "гитхаб", "issue", "pull request", "репозитор"),
    "git": (" git ", "репозитор", "коммит", "ветк"),
    "filesystem": ("файловая система", "файл", "папк", "директор"),
    "websearch": ("поиск в интернете", "в сети", "web search"),
    "gdrive": ("google drive", "гугл драйв", "gdrive"),
    "slack": ("slack", "слак", "канал"),
    "jira": ("jira", "жира", "ticket"),
    "docker": ("docker", "докер", "контейнер"),
    "sqlite": ("sqlite", "sql", "база данных"),
    "postgres": ("postgres", "postgresql", "база данных"),
}


FALLBACK_ACTION_TOOLS = (
    "write_in_application",
    "open_application",
    "close_application",
    "list_active_windows",
    "search_files",
    "read_text_file",
    "write_text_file",
    "apply_text_patch",
    "inspect_project",
    "search_web_tavily",
    "browser_open_url",
    "browser_get_page_text",
    "run_terminal_command",
    "start_process",
    "get_process_status",
    "execute_plan",
    "start_background_plan",
    "get_clipboard_content",
    "set_clipboard_content",
    "get_system_status",
    "search_in_memory",
)

BASIC_TOOLS = (
    "get_current_time",
    "get_system_status",
    "search_web_tavily",
    "search_in_memory",
)

TOKEN_STOPWORDS = {
    "the", "and", "for", "with", "from", "tool", "using",
    "для", "или", "при", "это", "этот", "эта", "выполняет", "возвращает",
    "инструмент", "пользователь", "данные",
}


def extract_mcp_server_name(tool_name: str) -> str | None:
    """Извлекает имя сервера из ``mcp_{server}_{tool}``."""
    if not tool_name.startswith("mcp_"):
        return None

    rest = tool_name[4:]
    if not rest:
        return None

    server_name = rest.split("_", 1)[0]
    return server_name or None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower().replace("ё", "е")).strip()


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zа-я0-9]{3,}", _normalize(text))
        if token not in TOKEN_STOPWORDS
    }


def _contains_any(text: str, markers: tuple[str, ...] | set[str]) -> bool:
    return any(marker in text for marker in markers)


def _schema_descriptions(
    schemas: list[dict[str, Any]] | None,
) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for schema in schemas or []:
        function = schema.get("function", {})
        name = function.get("name")
        if isinstance(name, str):
            descriptions[name] = str(function.get("description") or "")
    return descriptions


def select_tools_for_request(
    request_text: str,
    available_tool_names: set[str],
    max_tools: int = 20,
    has_image: bool = False,
    *,
    tool_descriptions: Mapping[str, str] | None = None,
    broaden: bool = False,
) -> set[str]:
    """Возвращает ранжированный по релевантности ограниченный набор tools."""
    if max_tools <= 0:
        return set()

    available = set(available_tool_names)
    normally_visible = filter_tools_for_model(available)
    lowered = _normalize(request_text)
    request_tokens = _tokens(lowered)
    scores: dict[str, int] = {}
    priority = {
        name: index
        for index, name in enumerate((*FALLBACK_ACTION_TOOLS, *BASIC_TOOLS))
    }

    def add(tool_name: str, score: int) -> None:
        if tool_name in normally_visible:
            scores[tool_name] = max(scores.get(tool_name, 0), score)

    for tool_name, keywords in KEYWORDS_BY_TOOL.items():
        if _contains_any(lowered, keywords):
            add(tool_name, 100)

    for markers, tool_names in CAPABILITY_GROUPS:
        if _contains_any(lowered, markers):
            for tool_name in tool_names:
                add(tool_name, 70)

    # Имена особенно полезны для MCP и англоязычных команд.
    for tool_name in normally_visible:
        name_tokens = {
            token
            for token in tool_name.lower().split("_")
            if len(token) >= 3 and token not in {"mcp", "tool"}
        }
        overlap = request_tokens & name_tokens
        if overlap:
            add(tool_name, 35 + 8 * len(overlap))

        description = (tool_descriptions or {}).get(tool_name, "")
        description_overlap = request_tokens & _tokens(description)
        if description_overlap:
            add(tool_name, 20 + min(20, 4 * len(description_overlap)))

        server_name = extract_mcp_server_name(tool_name)
        if server_name is None:
            continue

        aliases = MCP_SERVER_ALIASES.get(server_name, (server_name,))
        if _contains_any(f" {lowered} ", aliases):
            add(tool_name, 90)

    # Примитивы скрыты по умолчанию, но должны стать доступны, когда именно
    # они являются единственным честным способом выполнить явную GUI-команду.
    for tool_name, markers in GUI_PRIMITIVE_MARKERS.items():
        if tool_name in available and _contains_any(lowered, markers):
            scores[tool_name] = max(scores.get(tool_name, 0), 95)

    if has_image:
        for tool_name in (
            "get_active_window_ui_tree", "get_ui_tree", "find_ui_element",
            "ocr_screen", "find_text_on_screen", "click_text",
        ):
            if tool_name in available:
                scores[tool_name] = max(scores.get(tool_name, 0), 85)

    action_requested = _contains_any(f"{lowered} ", ACTION_MARKERS)

    if broaden or (action_requested and len(scores) < 6):
        for index, tool_name in enumerate(FALLBACK_ACTION_TOOLS):
            add(tool_name, max(8, 30 - index))

    if not scores:
        for index, tool_name in enumerate(BASIC_TOOLS):
            add(tool_name, 20 - index)

    ranked = sorted(
        scores,
        key=lambda name: (
            -scores[name],
            priority.get(name, len(priority)),
            name,
        ),
    )
    return set(ranked[:max_tools])


def get_tool_schemas_for_request(
    request_text: str,
    registry_schemas: list[dict[str, Any]],
    max_tools: int = 20,
    *,
    has_image: bool = False,
    broaden: bool = False,
) -> list[dict[str, Any]]:
    """Фильтрует схемы, используя также их реальные описания."""
    available_names = {
        schema["function"]["name"]
        for schema in registry_schemas
        if isinstance(schema.get("function", {}).get("name"), str)
    }
    selected_names = select_tools_for_request(
        request_text,
        available_names,
        max_tools,
        has_image,
        tool_descriptions=_schema_descriptions(registry_schemas),
        broaden=broaden,
    )
    return [
        schema
        for schema in registry_schemas
        if schema.get("function", {}).get("name") in selected_names
    ]


def get_selected_tool_names(
    request_text: str,
    all_tool_names: set[str] | None = None,
    has_image: bool = False,
    *,
    max_tools: int = 20,
    tool_schemas: list[dict[str, Any]] | None = None,
    broaden: bool = False,
) -> set[str]:
    """Упрощённый интерфейс выбора имён инструментов."""
    if all_tool_names is None:
        return {
            "get_current_time",
            "get_system_status",
            "search_web_tavily",
            "search_in_memory",
            "open_application",
            "close_application",
            "type_text",
            "open_and_focus",
            "write_in_application",
        }

    return select_tools_for_request(
        request_text,
        all_tool_names,
        max_tools,
        has_image,
        tool_descriptions=_schema_descriptions(tool_schemas),
        broaden=broaden,
    )


# Alias for backward compatibility
select_tool_names = get_selected_tool_names
