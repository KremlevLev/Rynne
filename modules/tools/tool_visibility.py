# modules/tools/tool_visibility.py
"""
Tool Visibility - управление видимостью инструментов для модели.

Публичные навыки - видимы модели напрямую.
Внутренние примитивы - скрыты, используются через skills.
Recovery tools - только для восстановления после ошибок.
"""
from __future__ import annotations


# Публичные навыки - видимы модели напрямую
PUBLIC_SKILLS = frozenset({
    "write_in_application",
    "create_obsidian_note",
    "run_project_tests",
    "start_development_server",
    "edit_file_transactionally",
    "browser_research",
    "open_telegram_chat",
})

# Внутренние примитивы - скрыты от модели
INTERNAL_PRIMITIVES = frozenset({
    "focus_window",
    "press_keyboard_combination",
    "type_text",
    "mouse_click",
})

# Recovery tools - только для восстановления
RECOVERY_TOOLS = frozenset({
    "get_ui_tree",
    "find_ui_element",
    "ocr_screen",
    "click_text",
})


def is_public_skill(tool_name: str) -> bool:
    """Проверяет, является ли инструмент публичным навыком."""
    return tool_name in PUBLIC_SKILLS


def is_internal_primitive(tool_name: str) -> bool:
    """Проверяет, является ли инструмент внутренним примитивом."""
    return tool_name in INTERNAL_PRIMITIVES


def is_recovery_tool(tool_name: str) -> bool:
    """Проверяет, является ли инструмент инструментом восстановления."""
    return tool_name in RECOVERY_TOOLS


def filter_tools_for_model(
    tool_names: set[str],
) -> set[str]:
    """
    Фильтрует инструменты для передачи модели.

    Возвращает только публичные навыки и обычные инструменты,
    исключая внутренние примитивы.
    """
    return {
        name
        for name in tool_names
        if is_public_skill(name) or not is_internal_primitive(name)
    }
