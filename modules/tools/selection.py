# modules/tools/selection.py
"""Dynamic Tool Selection - выбор только релевантных инструментов для модели.

Позволяет не передавать всю категорию инструментов модели, а выбирать
только те, которые действительно нужны для конкретного запроса.
"""
from __future__ import annotations

import re
from typing import Any

from modules.tools.tool_visibility import (
    filter_tools_for_model,
    is_public_skill,
)


# Ключевые слова для категорий инструментов
KEYWORDS_BY_TOOL: dict[str, set[str]] = {
    # Время и система
    "get_current_time": {"время", "дата", "час", "минут", "сегодня", "сейчас"},
    "get_system_status": {"система", "память", "оперативка", "cpu", "батарея", "загрузка"},
    
    # Приложения и окна
    "open_application": {"открыть", "запустить", "включить", "xром", "хром", "блокнот", "калькулятор"},
    "close_application": {"закрыть", "выключить", "остановить"},
    "focus_window": {"фокус", "окно", "переключить"},
    "list_active_windows": {"список окон", "активные окна", "что запущено"},
    "manage_windows": {"свернуть", "развернуть", "окна"},
    
    # Текст и ввод
    "type_text": {"напечатать", "ввести", "написать", "текст"},
    "press_keyboard_combination": {"клавиш", "горячая", "ctrl", "alt", "tab"},
    
    # Веб
    "search_web_tavily": {"найти", "поиск", "информация", "интернет"},
    "scrape_webpage": {"скрейп", "страница", "сайт", "webpage"},
    "open_website": {"сайт", "перейти", "open website"},
    
    # Файлы
    "read_text_file": {"прочитать", "файл", "документ", "readme"},
    "write_text_file": {"записать", "создать файл", "сохранить"},
    "search_files": {"поиск файлов", "найти файл", "locate"},
    
    # Память
    "save_to_memory": {"запомни", "запомнить", "записать в память"},
    "search_in_memory": {"вспомни", "найти в памяти", "что помнишь"},
    
    # Браузер
    "browser_start": {"браузер", "browser"},
    "browser_open_url": {"открыть url", "перейти по ссылке"},
    "browser_click": {"клик", "нажать кнопку"},
    "browser_fill": {"заполнить", "form", "поле"},
    "browser_screenshot": {"скриншот", "снимок"},
    
    # Git и проекты
    "git_status": {"git", "статус", "status"},
    "git_log": {"лог", "коммиты", "commits"},
    "git_branch": {"ветка", "branch"},
    "git_diff": {"изменения", "diff"},
    "git_commit": {"закоммить", "commit"},
    "inspect_project": {"проект", "структура", "entry point"},
    
    # Планирование
    "execute_plan": {"план", "выполни", "задача"},
    "start_background_plan": {"фон", "background", "асинхронно"},
    
    # MCP серверы (ключевые слова для динамического включения)
    "mcp_github": {"github", "репозиторий", "issue", "pr", "репо"},
    "mcp_slack": {"slack", "канал", "сообщение", "чат"},
    "mcp_gdrive": {"google drive", "гугл драйв", "gdrive", "документ"},
    "mcp_filesystem": {"файловая система", "директория", "папка"},
    "mcp_sqlite": {"sql", "sqlite", "query", "запрос"},
    "mcp_postgres": {"postgres", "postgresql", "база данных"},
    "mcp_git": {"git", "репозиторий", "мне", "branch"},
    "mcp_docker": {"docker", "контейнер", "nginx", "container"},
    "mcp_jira": {"jira", "задача", "таск", "ticket"},
    "mcp_websearch": {"поиск", "search", "найти в интернете"},
}


def extract_mcp_server_name(tool_name: str) -> str | None:
    """
    Извлекает имя сервера из имени MCP инструмента.
    
    Формат: mcp_{server_name}_{tool_name}
    Пример: mcp_github_list_repos -> github
    
    Args:
        tool_name: Полное имя инструмента
        
    Returns:
        Имя сервера или None если не MCP инструмент
    """
    if not tool_name.startswith("mcp_"):
        return None
    
    # Убираем префикс mcp_
    rest = tool_name[4:]  # "mcp_" = 4 chars
    
    if not rest:
        return None
    
    # Ищем второй подчерк: mcp_{server}_{tool}
    parts = rest.split("_", 1)
    if len(parts) >= 1 and parts[0]:
        return parts[0]
    
    return None


def select_tools_for_request(
    request_text: str,
    available_tool_names: set[str],
    max_tools: int = 20,
    has_image: bool = False,
) -> set[str]:
    """
    Выбирает релевантные инструменты для конкретного запроса.
    
    Args:
        request_text: Текст запроса пользователя
        available_tool_names: Все доступные инструменты
        max_tools: Максимальное количество инструментов для передачи
        has_image: Есть ли изображение в запросе (для vision-инструментов)
        
    Returns:
        Набор имён релевантных инструментов
    """
    filtered = filter_tools_for_model(available_tool_names)
    lowered = request_text.lower()
    
    # Сначала добавляем инструменты с подходящими ключевыми словами
    selected: set[str] = set()
    
    for tool_name, keywords in KEYWORDS_BY_TOOL.items():
        if tool_name not in filtered:
            continue
        if any(kw in lowered for kw in keywords):
            selected.add(tool_name)
    
    # MCP инструменты - проверяем по имени сервера
    mcp_servers_mentioned: set[str] = set()
    for tool_name in filtered:
        server_name = extract_mcp_server_name(tool_name)
        if server_name and (server_name in lowered or f" {server_name}" in f" {lowered} "):
            selected.add(tool_name)
            mcp_servers_mentioned.add(server_name)
    
    # Если ничего не найдено, возвращаем базовый набор
    if not selected:
        basic_tools = {
            "get_current_time",
            "get_system_status",
            "search_web_tavily",
            "search_in_memory",
        }
        selected = {t for t in basic_tools if t in filtered}
    
    # Ограничиваем количество
    if len(selected) > max_tools:
        selected = set(sorted(selected)[:max_tools])
    
    return selected


def get_tool_schemas_for_request(
    request_text: str,
    registry_schemas: list[dict[str, Any]],
    max_tools: int = 20,
) -> list[dict[str, Any]]:
    """
    Возвращает только релевантные схемы инструментов для запроса.
    
    Args:
        request_text: Текст запроса
        registry_schemas: Все схемы инструментов из реестра
        max_tools: Максимальное количество
        
    Returns:
        Список схем для передачи модели
    """
    available_names = {
        schema["function"]["name"]
        for schema in registry_schemas
    }
    selected_names = select_tools_for_request(request_text, available_names, max_tools)
    
    return [
        schema
        for schema in registry_schemas
        if schema["function"]["name"] in selected_names
    ]


def get_selected_tool_names(
    request_text: str,
    all_tool_names: set[str] | None = None,
    has_image: bool = False,
) -> set[str]:
    """
    Упрощённый интерфейс для получения имён инструментов.
    
    Если all_tool_names не передан, используется базовый набор инструментов.
    """
    if all_tool_names is None:
        # Возвращаем базовые инструменты для тестов
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
    return select_tools_for_request(request_text, all_tool_names, has_image=has_image)


# Alias for backward compatibility
select_tool_names = get_selected_tool_names
