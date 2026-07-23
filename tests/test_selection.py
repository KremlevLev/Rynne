# tests/test_selection.py
"""Tests for Dynamic Tool Selection."""
from __future__ import annotations

from modules.tools.selection import (
    select_tools_for_request,
    get_tool_schemas_for_request,
    get_selected_tool_names,
    KEYWORDS_BY_TOOL,
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
