# tests/test_selection.py
"""Tests for Dynamic Tool Selection."""
from __future__ import annotations

from modules.tools.selection import (
    select_tools_for_request,
    get_tool_schemas_for_request,
    get_selected_tool_names,
    KEYWORDS_BY_TOOL,
    request_prefers_interactive_browser,
    request_requires_user_browser_session,
)
from modules.tools.tool_visibility import (
    filter_tools_for_model,
)


def test_select_tools_for_simple_time_request() -> None:
    """Test selection for time-related request."""
    available = {
        "get_current_time",
        "get_system_status",
        "search_web_tavily",
    }
    
    result = select_tools_for_request("Какое сейчас время?", available)
    
    assert "get_current_time" in result


def test_select_tools_for_system_request() -> None:
    """Test selection for system status request."""
    available = {
        "get_current_time",
        "get_system_status",
        "search_web_tavily",
    }
    
    result = select_tools_for_request("Покажи загрузку CPU и памяти", available)
    
    assert "get_system_status" in result


def test_select_tools_for_web_request() -> None:
    """Test selection for web search request."""
    available = {
        "get_current_time",
        "search_web_tavily",
        "scrape_webpage",
    }
    
    result = select_tools_for_request("Найди информацию обо мне в интернете", available)
    
    assert "search_web_tavily" in result


def test_select_tools_for_memory_request() -> None:
    """Test selection for memory request."""
    available = {
        "save_to_memory",
        "search_in_memory",
    }
    
    result = select_tools_for_request("Запомни что я люблю кофе", available)
    assert "save_to_memory" in result
    
    result = select_tools_for_request("Что ты знаешь обо мне?", available)
    assert "search_in_memory" in result


def test_select_tools_max_limit() -> None:
    """Test that tool count is limited."""
    available = {
        f"tool_{i}" for i in range(100)
    }
    
    result = select_tools_for_request("test", available, max_tools=10)
    
    assert len(result) <= 10


def test_select_tools_filters_internal_primitives() -> None:
    """Test that internal primitives are filtered out."""
    from modules.tools.tool_visibility import INTERNAL_PRIMITIVES
    
    available = {
        "get_current_time",
        "type_text",
        "focus_window",
    }
    
    # INTERNAL_PRIMITIVES должны быть отфильтрованы
    result = select_tools_for_request("test", available)
    
    for primitive in INTERNAL_PRIMITIVES:
        if primitive in available:
            assert primitive not in result


def test_select_tools_empty_request_returns_basics() -> None:
    """Test that empty request returns basic tools."""
    available = {
        "get_current_time",
        "get_system_status",
        "search_web_tavily",
        "search_in_memory",
        "some_other_tool",
    }
    
    result = select_tools_for_request("", available)
    
    # Должны быть базовые инструменты
    assert "get_current_time" in result
    assert "get_system_status" in result


def test_get_selected_tool_names() -> None:
    """Test simplified interface."""
    available = {"get_current_time", "get_system_status"}
    
    result = get_selected_tool_names("сколько времени?", available)
    
    assert isinstance(result, set)
    assert "get_current_time" in result


def test_get_tool_schemas_for_request() -> None:
    """Test schema filtering."""
    schemas = [
        {"type": "function", "function": {"name": "get_current_time", "description": "Time"}},
        {"type": "function", "function": {"name": "get_system_status", "description": "Status"}},
    ]
    
    result = get_tool_schemas_for_request("время", schemas)
    
    assert len(result) == 1
    assert result[0]["function"]["name"] == "get_current_time"


def test_mcp_tool_selection() -> None:
    """Test MCP tool selection by server name."""
    available = {
        "mcp_github_list_issues",
        "mcp_github_create_issue",
        "mcp_sqlite_query",
    }
    
    result = select_tools_for_request("Найди репозитории на GitHub", available)
    
    # GitHub MCP инструменты должны быть включены
    assert "mcp_github_list_issues" in result
    assert "mcp_github_create_issue" in result


def test_select_tools_applies_visibility_filter() -> None:
    """Test that visibility filter is applied."""
    available = {
        "get_current_time",
        "search_web_tavily",
    }
    
    result = select_tools_for_request("test", available)
    
    # Все результаты должны пройти через filter_tools_for_model
    for tool_name in result:
        assert tool_name in filter_tools_for_model(available)


def test_extract_mcp_server_name() -> None:
    """Test MCP server name extraction."""
    from modules.tools.selection import extract_mcp_server_name
    
    # MCP инструменты
    assert extract_mcp_server_name("mcp_github_list_issues") == "github"
    assert extract_mcp_server_name("mcp_github_create_issue") == "github"
    assert extract_mcp_server_name("mcp_sqlite_query") == "sqlite"
    assert extract_mcp_server_name("mcp_docker_list_containers") == "docker"
    
    # Не MCP инструменты
    assert extract_mcp_server_name("get_current_time") is None
    assert extract_mcp_server_name("search_web_tavily") is None
    
    # Edge cases
    assert extract_mcp_server_name("mcp_") is None
    assert extract_mcp_server_name("mcp_single") == "single"


def test_mcp_tool_selection_multiple_servers() -> None:
    """Test MCP tool selection with multiple servers mentioned."""
    available = {
        "mcp_github_list_issues",
        "mcp_github_create_issue",
        "mcp_sqlite_query",
        "mcp_docker_ps",
    }
    
    result = select_tools_for_request("Найди issues на GitHub и выполни sqlite запрос", available)
    
    # GitHub и SQLite инструменты должны быть включены
    assert "mcp_github_list_issues" in result
    assert "mcp_sqlite_query" in result


def test_mcp_tool_selection_no_server_mentioned() -> None:
    """Test MCP tool selection when no server is mentioned."""
    available = {
        "mcp_github_list_issues",
        "mcp_sqlite_query",
        "get_current_time",
    }
    
    result = select_tools_for_request("Какое время?", available)
    
    # MCP инструменты не должны быть включены (нет упоминания сервера)
    assert "mcp_github_list_issues" not in result
    assert "mcp_sqlite_query" not in result
    # Но базовые должны быть
    assert "get_current_time" in result


def test_keywords_by_tool_exists() -> None:
    """Test that keyword mapping exists."""
    assert "get_current_time" in KEYWORDS_BY_TOOL
    assert "время" in KEYWORDS_BY_TOOL["get_current_time"]
    assert "get_system_status" in KEYWORDS_BY_TOOL
    assert "память" in KEYWORDS_BY_TOOL["get_system_status"]


def test_unknown_action_gets_capability_fallback() -> None:
    available = {
        "get_current_time",
        "get_system_status",
        "search_web_tavily",
        "read_text_file",
        "write_text_file",
        "run_terminal_command",
        "execute_plan",
    }

    result = select_tools_for_request(
        "Сделай это и проверь результат",
        available,
    )

    assert "read_text_file" in result
    assert "write_text_file" in result
    assert "execute_plan" in result


def test_safe_undo_is_selected_only_for_explicit_rollback() -> None:
    available = {
        "write_text_file",
        "run_terminal_command",
        "undo_last_file_change",
    }

    undo_result = select_tools_for_request(
        "Отмени последнее изменение файла",
        available,
    )
    test_result = select_tools_for_request(
        "Запусти pytest в проекте",
        available,
    )

    assert "undo_last_file_change" in undo_result
    assert "undo_last_file_change" not in test_result


def test_explicit_hotkey_request_can_use_atomic_primitive() -> None:
    available = {
        "get_current_time",
        "press_keyboard_combination",
    }

    result = select_tools_for_request(
        "Нажми Ctrl+S",
        available,
    )

    assert "press_keyboard_combination" in result


def test_image_request_includes_available_recovery_tools() -> None:
    available = {
        "get_current_time",
        "ocr_screen",
        "find_ui_element",
    }

    result = select_tools_for_request(
        "Разбери ошибку на скриншоте",
        available,
        has_image=True,
    )

    assert "ocr_screen" in result
    assert "find_ui_element" in result


def test_schema_description_participates_in_ranking() -> None:
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "custom_diagnostics",
                "description": "Проверяет состояние Docker контейнеров.",
            },
        },
        {
            "type": "function",
            "function": {
                "name": "unrelated_action",
                "description": "Управляет музыкальным проигрывателем.",
            },
        },
    ]

    result = get_tool_schemas_for_request(
        "Проверь Docker контейнеры",
        schemas,
        max_tools=1,
    )

    assert result[0]["function"]["name"] == "custom_diagnostics"


def test_semantic_ranking_wins_before_limit() -> None:
    available = {
        "aaa_unrelated",
        "browser_open_url",
        "zzz_unrelated",
    }

    result = select_tools_for_request(
        "Открой сайт",
        available,
        max_tools=1,
    )

    assert result == {"browser_open_url"}


def test_interactive_account_navigation_excludes_search_substitute() -> None:
    available = {
        "browser_open_url",
        "browser_get_page_text",
        "browser_click",
        "search_web_tavily",
        "scrape_webpage",
        "open_website",
    }
    request = "Открой OpenRouter и там мою активность"

    result = select_tools_for_request(
        request,
        available,
        broaden=True,
    )

    assert request_prefers_interactive_browser(request)
    assert "browser_open_url" in result
    assert "browser_get_page_text" in result
    assert "search_web_tavily" not in result
    assert "scrape_webpage" not in result
    assert "open_website" not in result


def test_google_signup_uses_regular_chrome_and_excludes_playwright() -> None:
    request = (
        "Открой notion.so, зарегистрируй новый аккаунт через Google, "
        "создай workspace Rynne Test"
    )
    available = {
        "open_url_in_browser", "list_active_windows", "focus_window",
        "inspect_active_window", "click_ui_element",
        "press_keyboard_combination", "type_text", "get_ui_tree",
        "find_ui_element", "ocr_screen", "click_text", "mouse_click",
        "browser_start", "browser_open_url", "browser_get_page_text",
        "browser_click", "browser_fill", "browser_screenshot",
    }

    result = select_tools_for_request(request, available, max_tools=20)

    assert request_requires_user_browser_session(request)
    assert "open_url_in_browser" in result
    assert "focus_window" in result
    assert "inspect_active_window" in result
    assert "click_ui_element" in result
    assert "get_ui_tree" in result
    assert not any(name.startswith("browser_") for name in result)


def test_broadened_unknown_public_action_can_research_before_clarifying() -> None:
    available = {"open_application", "search_web_tavily", "get_system_status"}

    result = select_tools_for_request(
        "Настрой новый сервис CloudWhistle и подключи его API",
        available,
        max_tools=2,
        broaden=True,
    )

    assert "search_web_tavily" in result


def test_broadened_private_action_does_not_promote_web_search() -> None:
    available = {"search_web_tavily", "mcp_telegram_business_send_message"}

    result = select_tools_for_request(
        "Отправь личное сообщение контакту Влад в Telegram",
        available,
        max_tools=1,
        broaden=True,
    )

    assert result == {"mcp_telegram_business_send_message"}


def test_openrouter_activity_uses_browser_session_and_screenshot() -> None:
    available = {
        "open_application",
        "write_in_application",
        "browser_open_url",
        "browser_get_page_text",
        "browser_click",
        "browser_screenshot",
        "search_web_tavily",
    }
    request = (
        "Включи в браузере OpenRouter и там чекни мою "
        "активность, сделав скрин"
    )

    result = select_tools_for_request(request, available, broaden=True)

    assert "browser_open_url" in result
    assert "browser_get_page_text" in result
    assert "browser_screenshot" in result
    assert "open_application" not in result
    assert "write_in_application" not in result
    assert "search_web_tavily" not in result
