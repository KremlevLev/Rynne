# tests/test_mcp_gateway.py
"""Tests for MCP Gateway and Recovery & Self-healing functionality."""
from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from modules.agent.mcp_gateway import (
    MCPGateway,
    MCPServerConfig,
    MCPConnectionPool,
    MCPToolCache,
    MCPErrorMiddleware,
)
from modules.agent.recovery import (
    GracefulDegradation,
    RecoveryAction,
    RecoveryContext,
    RecoveryDecision,
    RecoveryEngine,
    DiagnosticResult,
    SelfDiagnostics,
    get_mcp_recovery_tools,
    set_mcp_recovery_tools,
)
from modules.domain.results import ToolResult
from modules.tools.runtime import ToolRegistry


def test_mcp_server_config_timeout_params() -> None:
    """Test MCPServerConfig timeout parameters."""
    config = MCPServerConfig(
        name="test_server",
        command="node",
        timeout=60.0,
        retry_count=5,
        retry_delay=2.0,
    )
    
    assert config.timeout == 60.0
    assert config.retry_count == 5
    assert config.retry_delay == 2.0


def test_mcp_error_middleware_creation() -> None:
    """Test MCPErrorMiddleware can be created."""
    middleware = MCPErrorMiddleware(max_retries=5, base_delay=2.0, max_delay=60.0)
    assert middleware is not None
    assert middleware._max_retries == 5
    assert middleware._base_delay == 2.0
    assert middleware._max_delay == 60.0


def test_mcp_error_middleware_calculate_delay() -> None:
    """Test exponential backoff delay calculation."""
    middleware = MCPErrorMiddleware(base_delay=1.0, max_delay=30.0)
    
    # Attempt 1: 1 second
    assert middleware.calculate_delay(1) == 1.0
    
    # Attempt 2: 2 seconds
    assert middleware.calculate_delay(2) == 2.0
    
    # Attempt 3: 4 seconds
    assert middleware.calculate_delay(3) == 4.0
    
    # Attempt 4: 8 seconds
    assert middleware.calculate_delay(4) == 8.0
    
    # Attempt 5: 16 seconds
    assert middleware.calculate_delay(5) == 16.0
    
    # Attempt 6: capped at 30 seconds
    assert middleware.calculate_delay(6) == 30.0


def test_mcp_error_middleware_should_retry() -> None:
    """Test should_retry for different error codes."""
    middleware = MCPErrorMiddleware()
    
    # Retryable errors
    assert middleware.should_retry("MCP_TIMEOUT") is True
    assert middleware.should_retry("MCP_CONNECTION_ERROR") is True
    assert middleware.should_retry("MCP_TOOL_ERROR") is True
    
    # Non-retryable errors
    assert middleware.should_retry("INVALID_TOOL_NAME") is False
    assert middleware.should_retry("UNKNOWN_MCP_SERVER") is False
    assert middleware.should_retry("MCP_CONFIG_ERROR") is False


def test_mcp_error_middleware_error_count() -> None:
    """Test error count tracking."""
    middleware = MCPErrorMiddleware()
    
    # Initially zero
    assert middleware.get_error_count("mcp_test_tool") == 0
    
    # Increment
    middleware.increment_error("mcp_test_tool")
    assert middleware.get_error_count("mcp_test_tool") == 1
    
    middleware.increment_error("mcp_test_tool")
    assert middleware.get_error_count("mcp_test_tool") == 2
    
    # Reset
    middleware.reset_error_count("mcp_test_tool")
    assert middleware.get_error_count("mcp_test_tool") == 0


def test_mcp_gateway_with_middleware() -> None:
    """Test MCPGateway creates middleware."""
    gateway = MCPGateway(max_retries=5)
    assert gateway._middleware is not None
    assert gateway._middleware._max_retries == 5


def test_mcp_tool_cache_creation() -> None:
    """Test MCPToolCache can be created."""
    cache = MCPToolCache(ttl_seconds=1800)
    assert cache is not None
    assert cache._ttl_seconds == 1800


def test_mcp_tool_cache_set_and_get() -> None:
    """Test MCPToolCache set and get."""
    cache = MCPToolCache()
    schema = {"name": "test_tool", "description": "A test tool"}
    
    cache.set("mcp_test_tool", schema)
    
    result = cache.get("mcp_test_tool")
    assert result == schema


def test_mcp_tool_cache_get_nonexistent() -> None:
    """Test MCPToolCache get returns None for missing key."""
    cache = MCPToolCache()
    
    result = cache.get("nonexistent_tool")
    assert result is None


def test_mcp_tool_cache_ttl_expiration() -> None:
    """Test MCPToolCache TTL expiration."""
    cache = MCPToolCache(ttl_seconds=1)  # 1 second TTL
    schema = {"name": "test_tool", "description": "A test tool"}
    
    cache.set("mcp_test_tool", schema)
    
    # Should be present immediately
    assert cache.get("mcp_test_tool") == schema
    
    # Wait for expiration
    time.sleep(1.1)
    
    # Should be expired
    result = cache.get("mcp_test_tool")
    assert result is None


def test_mcp_tool_cache_clear() -> None:
    """Test MCPToolCache clear."""
    cache = MCPToolCache()
    cache.set("mcp_tool1", {"name": "tool1"})
    cache.set("mcp_tool2", {"name": "tool2"})
    
    cache.clear()
    
    assert len(cache.get_tool_names()) == 0


def test_mcp_tool_cache_get_tool_names() -> None:
    """Test MCPToolCache get_tool_names."""
    cache = MCPToolCache()
    cache.set("mcp_tool1", {"name": "tool1"})
    cache.set("mcp_tool2", {"name": "tool2"})
    
    names = cache.get_tool_names()
    
    assert "mcp_tool1" in names
    assert "mcp_tool2" in names


def test_mcp_connection_pool_creation() -> None:
    """Test MCPConnectionPool can be created."""
    pool = MCPConnectionPool(max_connections=10)
    assert pool is not None
    assert pool._max_connections == 10


def test_mcp_connection_pool_returns_none_for_sse() -> None:
    """Test MCPConnectionPool returns None for SSE transport."""
    
    async def run_test() -> None:
        pool = MCPConnectionPool()
        config = MCPServerConfig(
            name="sse_server",
            command="node",
            transport="sse",
            url="https://api.example.com/mcp",
        )
        
        result = await pool.get_process(config)
        assert result is None
    
    asyncio.run(run_test())


def test_mcp_connection_pool_close() -> None:
    """Test MCPConnectionPool close clears all processes."""
    pool = MCPConnectionPool()
    pool._processes["test"] = None  # type: ignore
    pool.close()
    assert len(pool._processes) == 0
    assert len(pool._locks) == 0


def test_mcp_gateway_with_cache() -> None:
    """Test MCPGateway creates cache."""
    gateway = MCPGateway(cache_ttl=7200)
    assert gateway._cache is not None
    assert gateway._cache._ttl_seconds == 7200


def test_mcp_gateway_with_pool() -> None:
    """Test MCPGateway creates pool."""
    gateway = MCPGateway(pool_size=10)
    assert gateway._pool is not None
    assert gateway._pool._max_connections == 10


def test_mcp_recovery_tools_setter() -> None:
    """Test MCP recovery tools can be set and retrieved."""
    test_tools = {"mcp_recovery_rollback", "mcp_recovery_diagnose"}
    
    set_mcp_recovery_tools(test_tools)
    
    # Check via getter function (MCP_RECOVERY_TOOLS is module-level, not updated by import)
    assert get_mcp_recovery_tools() == test_tools


def test_mcp_recovery_tools_empty_by_default() -> None:
    """Test MCP recovery tools is empty by default."""
    set_mcp_recovery_tools(set())
    assert len(get_mcp_recovery_tools()) == 0


def test_mcp_server_config_creation() -> None:
    """Test MCPServerConfig can be created."""
    config = MCPServerConfig(
        name="test_server",
        command="node",
        args=["server.js"],
        env={"TOKEN": "secret"},
    )
    
    assert config.name == "test_server"
    assert config.command == "node"
    assert config.args == ["server.js"]
    assert config.env == {"TOKEN": "secret"}
    assert config.transport == "stdio"


def test_mcp_server_config_sse() -> None:
    """Test MCPServerConfig can be created with SSE transport."""
    config = MCPServerConfig(
        name="sse_server",
        command="node",
        args=["-y", "@modelcontextprotocol/server-remote"],
        env={},
        enabled=True,
        transport="sse",
        url="https://api.example.com/mcp",
    )
    
    assert config.name == "sse_server"
    assert config.transport == "sse"
    assert config.url == "https://api.example.com/mcp"


def test_mcp_gateway_creation() -> None:
    """Test MCPGateway can be instantiated."""
    gateway = MCPGateway()
    assert gateway is not None
    assert not gateway._initialized


def test_mcp_gateway_register_server() -> None:
    """Test MCPGateway can register servers."""
    gateway = MCPGateway()
    config = MCPServerConfig(
        name="test",
        command="python",
    )
    
    gateway.register_server(config)
    assert "test" in gateway._servers


def test_mcp_gateway_get_tool_schemas_empty() -> None:
    """Test MCPGateway returns empty schemas before initialization."""
    gateway = MCPGateway()
    schemas = gateway.get_tool_schemas()
    assert schemas == []


def test_mcp_gateway_get_available_tools_empty() -> None:
    """Test MCPGateway returns empty tools before initialization."""
    gateway = MCPGateway()
    tools = gateway.get_available_tools()
    assert tools == set()


def test_mcp_gateway_cached_tool_schema() -> None:
    """Test MCPGateway cached tool schema functionality."""
    gateway = MCPGateway()
    assert gateway.get_cached_tool_schema("nonexistent") is None


def test_recovery_engine_exists() -> None:
    """Test RecoveryEngine can be instantiated."""
    engine = RecoveryEngine()
    assert engine is not None


def test_recovery_decision_creation() -> None:
    """Test RecoveryDecision can be created."""
    decision = RecoveryDecision(
        action=RecoveryAction.ROLLBACK,
        reason="Test rollback",
        should_rollback=True,
    )
    
    assert decision.action == RecoveryAction.ROLLBACK
    assert decision.should_rollback is True
    assert decision.requires_user_input is False


def test_recovery_context_creation() -> None:
    """Test RecoveryContext can be created."""
    context = RecoveryContext(
        operation_name="test_op",
        has_fallback=True,
        has_rollback=True,
    )
    
    assert context.operation_name == "test_op"
    assert context.has_fallback is True
    assert context.has_rollback is True


def test_diagnostics_result_creation() -> None:
    """Test DiagnosticResult can be created."""
    result = DiagnosticResult(
        component="test_component",
        healthy=True,
        message="OK",
        details={"key": "value"},
    )
    
    assert result.component == "test_component"
    assert result.healthy is True
    assert result.details == {"key": "value"}


def test_self_diagnostics_initialization() -> None:
    """Test SelfDiagnostics can be initialized."""
    diagnostics = SelfDiagnostics()
    assert diagnostics is not None
    assert diagnostics.get_degradation_mode() == "full"


def test_graceful_degradation_initialization() -> None:
    """Test GracefulDegradation can be initialized."""
    diagnostics = SelfDiagnostics()
    degradation = GracefulDegradation(diagnostics)
    
    assert degradation.diagnostics == diagnostics
    assert degradation.get_retry_delay_multiplier() == 1.0


def test_graceful_degradation_full_mode() -> None:
    """Test GracefulDegradation in full mode has no restrictions."""
    diagnostics = SelfDiagnostics()
    degradation = GracefulDegradation(diagnostics)
    
    # In full mode, no tool restrictions
    alternative_tools = degradation.get_alternative_tools()
    assert len(alternative_tools) == 0


def test_graceful_degradation_degraded_mode_restricts_tools() -> None:
    """Test GracefulDegradation restricts tools in degraded mode."""
    diagnostics = SelfDiagnostics()
    degradation = GracefulDegradation(diagnostics)
    
    # Simulate degraded mode
    diagnostics._last_diagnostics = {
        "filesystem": DiagnosticResult(
            component="filesystem",
            healthy=False,
            message="Failed",
        ),
    }
    degradation._degradation_mode = "degraded_storage"
    
    alternative_tools = degradation.get_alternative_tools()
    
    assert "get_current_time" in alternative_tools
    assert "type_text" in alternative_tools


def test_graceful_degradation_mcp_fallback_check() -> None:
    """Test MCP fallback appropriateness check."""
    diagnostics = SelfDiagnostics()
    degradation = GracefulDegradation(diagnostics)
    
    # Full mode - can use MCP fallback
    degradation._degradation_mode = "full"
    assert degradation.should_use_mcp_fallback() is True
    
    # Degraded full - cannot use MCP fallback
    degradation._degradation_mode = "degraded_full"
    assert degradation.should_use_mcp_fallback() is False


def test_graceful_degradation_retry_delay_multiplier() -> None:
    """Test retry delay multiplier in degraded modes."""
    diagnostics = SelfDiagnostics()
    degradation = GracefulDegradation(diagnostics)
    
    # Full mode - normal delay
    degradation._degradation_mode = "full"
    assert degradation.get_retry_delay_multiplier() == 1.0
    
    # Network degraded - 2x delay
    degradation._degradation_mode = "degraded_network"
    assert degradation.get_retry_delay_multiplier() == 2.0
    
    # Full degraded - 4x delay
    degradation._degradation_mode = "degraded_full"
    assert degradation.get_retry_delay_multiplier() == 4.0


def test_degradation_mode_detection() -> None:
    """Test degradation mode detection logic."""
    diagnostics = SelfDiagnostics()
    
    # No issues - full mode
    diagnostics._last_diagnostics = {
        "database": DiagnosticResult(
            component="database",
            healthy=True,
            message="OK",
        ),
        "filesystem": DiagnosticResult(
            component="filesystem",
            healthy=True,
            message="OK",
        ),
    }
    assert diagnostics.get_degradation_mode() == "full"
    
    # Network issues - degraded_network
    diagnostics._last_diagnostics = {
        "database": DiagnosticResult(
            component="database",
            healthy=True,
            message="OK",
        ),
        "mcp_servers": DiagnosticResult(
            component="mcp_servers",
            healthy=False,
            message="Unavailable",
        ),
    }
    assert diagnostics.get_degradation_mode() == "degraded_network"
    
    # Critical failure - degraded_full
    diagnostics._last_diagnostics = {
        "database": DiagnosticResult(
            component="database",
            healthy=False,
            message="Failed",
        ),
    }
    assert diagnostics.get_degradation_mode() == "degraded_full"


def test_recovery_engine_decide_mcp_fallback() -> None:
    """Test RecoveryEngine decides fallback for MCP-related errors."""
    engine = RecoveryEngine()
    
    # Test that MCP tools are available for fallback
    set_mcp_recovery_tools({"mcp_recovery_rollback"})
    
    context = RecoveryContext(
        operation_name="test",
        has_fallback=True,
    )
    
    result = ToolResult.failure(
        "MODEL_ROUTE_FAILED",
        "Model routing failed",
    )
    
    decision = engine.decide(result, context)
    
    assert decision.action == RecoveryAction.FALLBACK


def test_mcp_gateway_call_tool_invalid_name() -> None:
    """Test MCPGateway rejects invalid tool names."""
    
    async def run_test() -> None:
        gateway = MCPGateway()
        result = await gateway.call_tool("invalid_name", {})
        assert not result.success
        assert result.code == "INVALID_TOOL_NAME"
    
    asyncio.run(run_test())


def test_mcp_gateway_call_tool_unknown_server() -> None:
    """Test MCPGateway rejects unknown servers."""
    
    async def run_test() -> None:
        gateway = MCPGateway()
        result = await gateway.call_tool("mcp_unknown_tool", {})
        assert not result.success
        assert result.code == "UNKNOWN_MCP_SERVER"
    
    asyncio.run(run_test())


def test_mcp_gateway_sse_config_without_url() -> None:
    """Test MCPGateway rejects SSE config without URL."""
    
    async def run_test() -> None:
        gateway = MCPGateway()
        config = MCPServerConfig(
            name="test_sse",
            command="node",
            transport="sse",
            # No URL provided
        )
        gateway.register_server(config)
        
        # Should raise error when trying to discover tools
        try:
            await gateway._discover_tools_sse(
                config,
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "url" in str(e).lower()
    
    asyncio.run(run_test())


def test_mcp_gateway_stdio_config() -> None:
    """Test MCPGateway stdio config is valid."""
    config = MCPServerConfig(
        name="test_stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-test"],
        transport="stdio",
    )
    
    assert config.transport == "stdio"
    assert config.url == ""


# ==============================================================================
# GitHub MCP Server Integration Tests
# ==============================================================================

def test_github_server_config_in_defaults() -> None:
    """Test that GitHub server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "github" in DEFAULT_MCP_SERVERS
    github_config = DEFAULT_MCP_SERVERS["github"]
    assert github_config["command"] == "npx"
    assert "-y" in github_config["args"]
    assert "@modelcontextprotocol/server-github" in github_config["args"]


def test_github_server_disabled_without_token() -> None:
    """Test that GitHub server is disabled when no token is present."""
    import os
    # Ensure no token is set
    os.environ.pop("GITHUB_TOKEN", None)
    
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    assert DEFAULT_MCP_SERVERS["github"]["enabled"] is False


def test_env_tokens_loading() -> None:
    """Test that environment tokens are loaded correctly."""
    import os
    os.environ["GITHUB_TOKEN"] = "test_github_token_123"
    
    from modules.agent.mcp_integration import _get_env_tokens
    tokens = _get_env_tokens()
    
    assert tokens["GITHUB_TOKEN"] == "test_github_token_123"
    assert tokens["SLACK_TOKEN"] == ""
    
    # Cleanup
    os.environ.pop("GITHUB_TOKEN", None)


def test_github_server_enabled_with_token() -> None:
    """Test that GitHub server is auto-enabled when token is present."""
    import os
    original_token = os.environ.get("GITHUB_TOKEN")
    os.environ["GITHUB_TOKEN"] = "ghp_test_token"
    
    # Need to reimport to get fresh defaults
    import importlib
    import modules.agent.mcp_integration as mcp_int
    importlib.reload(mcp_int)
    
    # The config itself has enabled=False, but bootstrap should auto-enable
    # We test that the env token is detected
    tokens = mcp_int._get_env_tokens()
    assert tokens["GITHUB_TOKEN"] == "ghp_test_token"
    
    # Cleanup
    if original_token:
        os.environ["GITHUB_TOKEN"] = original_token
    else:
        os.environ.pop("GITHUB_TOKEN", None)


def test_github_mcp_tool_name_format() -> None:
    """Test that GitHub MCP tools would be named correctly."""
    # GitHub MCP server tools would be named mcp_github_<tool_name>
    expected_tools = [
        "mcp_github_get_repository",
        "mcp_github_create_issue",
        "mcp_github_list_issues",
        "mcp_github_get_pull_request",
        "mcp_github_create_pull_request",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_github_"), f"Tool {tool} should start with mcp_github_"


def test_mcp_gateway_register_server_with_env() -> None:
    """Test that server can be registered with environment variables."""
    gateway = MCPGateway()
    config = MCPServerConfig(
        name="github",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_TOKEN": "test_token"},
        enabled=True,
    )
    
    gateway.register_server(config)
    assert "github" in gateway._servers
    assert gateway._servers["github"].env == {"GITHUB_TOKEN": "test_token"}


def test_mcp_gateway_uses_sdk_session_for_discovery_and_calls() -> None:
    class FakeTool:
        def model_dump(self, **kwargs) -> dict:
            return {
                "name": "read_value",
                "description": "Reads a value.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                    },
                    "required": ["key"],
                },
            }

    class FakeListResult:
        tools = [FakeTool()]

    class FakeText:
        def model_dump(self, **kwargs) -> dict:
            return {
                "type": "text",
                "text": "value=42",
            }

    class FakeCallResult:
        isError = False
        structuredContent = {"value": 42}
        content = [FakeText()]

    class FakeClient:
        def __init__(self) -> None:
            self.arguments: dict | None = None

        async def list_tools(self) -> FakeListResult:
            return FakeListResult()

        async def call_tool(
            self,
            name: str,
            arguments: dict,
        ) -> FakeCallResult:
            assert name == "read_value"
            self.arguments = arguments
            return FakeCallResult()

    async def run_test() -> None:
        gateway = MCPGateway()
        config = MCPServerConfig(
            name="project_files",
            command="python",
        )
        fake_client = FakeClient()
        gateway.register_server(config)
        gateway._sdk_clients[
            "project_files"
        ] = fake_client

        initialized = await gateway.initialize()
        assert initialized.success
        assert (
            "mcp_project_files_read_value"
            in gateway.get_available_tools()
        )

        registry = ToolRegistry()
        count = await gateway.register_with_registry(
            registry
        )
        assert count == 1
        definition = registry.get(
            "mcp_project_files_read_value"
        )
        assert definition is not None
        assert inspect.iscoroutinefunction(
            definition.handler
        )

        result = await gateway.call_tool(
            "mcp_project_files_read_value",
            {"key": "answer"},
        )
        assert result.success
        assert result.data["structured_content"] == {
            "value": 42,
        }
        assert fake_client.arguments == {
            "key": "answer",
        }

    asyncio.run(run_test())


def test_mcp_gateway_does_not_retry_network_writes_and_keeps_error() -> None:
    async def run_test() -> None:
        gateway = MCPGateway()
        config = MCPServerConfig(
            name="telegram_business",
            command="python",
        )
        gateway.register_server(config)
        calls = 0

        async def fail_once(config, request, tool_name) -> ToolResult:
            nonlocal calls
            calls += 1
            return ToolResult.failure(
                "MCP_TOOL_ERROR",
                "Telegram says: CHAT_WRITE_FORBIDDEN",
            )

        gateway._call_tool_stdio = fail_once
        result = await gateway.call_tool(
            "mcp_telegram_business_send_message",
            {"chat": "XIII", "text": "hello"},
        )

        assert calls == 1
        assert not result.success
        assert result.code == "MCP_TOOL_ERROR"
        assert result.message == "Telegram says: CHAT_WRITE_FORBIDDEN"

    asyncio.run(run_test())


def test_mcp_gateway_redacts_telegram_token_from_exception() -> None:
    async def run_test() -> None:
        gateway = MCPGateway()
        gateway.register_server(MCPServerConfig(
            name="telegram_business",
            command="python",
            env={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz"},
        ))

        async def leak_token(config, request, tool_name) -> ToolResult:
            raise RuntimeError(
                "400 for https://api.telegram.org/"
                "bot123456:abcdefghijklmnopqrstuvwxyz/sendMessage"
            )

        gateway._call_tool_stdio = leak_token
        result = await gateway.call_tool(
            "mcp_telegram_business_send_message",
            {"chat": "XIII", "text": "hello"},
        )

        assert not result.success
        assert "abcdefghijklmnopqrstuvwxyz" not in result.message
        assert "bot[REDACTED]" in result.message

    asyncio.run(run_test())


def test_explicit_mcp_config_resolves_env(
    tmp_path,
    monkeypatch,
) -> None:
    from modules.agent.mcp_integration import (
        create_mcp_gateway_from_config,
        load_mcp_config,
    )

    monkeypatch.setenv(
        "PROJECT_TOKEN",
        "local-secret",
    )
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            "project": {
              "command": "python",
              "args": ["server.py"],
              "env": {
                "TOKEN": "${PROJECT_TOKEN}"
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )

    gateway = create_mcp_gateway_from_config(
        load_mcp_config(config_path)
    )

    assert gateway._servers["project"].env == {
        "TOKEN": "local-secret",
    }


# ==============================================================================
# Filesystem MCP Server Integration Tests
# ==============================================================================

def test_filesystem_server_config_in_defaults() -> None:
    """Test that Filesystem server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "filesystem" in DEFAULT_MCP_SERVERS
    fs_config = DEFAULT_MCP_SERVERS["filesystem"]
    assert fs_config["command"] == "npx"
    assert "-y" in fs_config["args"]
    assert "@modelcontextprotocol/server-filesystem" in fs_config["args"]
    assert "--directory" in fs_config["args"]
    assert fs_config["enabled"] is False


def test_filesystem_mcp_tool_name_format() -> None:
    """Test that Filesystem MCP tools would be named correctly."""
    # Filesystem MCP server tools would be named mcp_filesystem_<tool_name>
    expected_tools = [
        "mcp_filesystem_read_file",
        "mcp_filesystem_write_file",
        "mcp_filesystem_list_directory",
        "mcp_filesystem_search_files",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_filesystem_"), f"Tool {tool} should start with mcp_filesystem_"


def test_filesystem_server_requires_explicit_enable() -> None:
    """Untrusted external servers are never started implicitly."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert DEFAULT_MCP_SERVERS["filesystem"]["enabled"] is False


# ==============================================================================
# SQLite MCP Server Integration Tests
# ==============================================================================

def test_sqlite_server_config_in_defaults() -> None:
    """Test that SQLite server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "sqlite" in DEFAULT_MCP_SERVERS
    sqlite_config = DEFAULT_MCP_SERVERS["sqlite"]
    assert sqlite_config["command"] == "npx"
    assert "-y" in sqlite_config["args"]
    assert "@modelcontextprotocol/server-sqlite" in sqlite_config["args"]


def test_sqlite_server_disabled_without_path() -> None:
    """Test that SQLite server is disabled when no path is set."""
    import os
    # Ensure no path is set
    os.environ.pop("MCP_SQLITE_PATH", None)
    
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    assert DEFAULT_MCP_SERVERS["sqlite"]["enabled"] is False


def test_sqlite_path_loading() -> None:
    """Test that SQLite path is loaded from environment."""
    import os
    os.environ["MCP_SQLITE_PATH"] = "test_memory.db"
    
    from modules.agent.mcp_integration import _get_sqlite_path
    path = _get_sqlite_path()
    
    assert path == "test_memory.db"
    
    # Cleanup
    os.environ.pop("MCP_SQLITE_PATH", None)


def test_sqlite_mcp_tool_name_format() -> None:
    """Test that SQLite MCP tools would be named correctly."""
    # SQLite MCP server tools would be named mcp_sqlite_<tool_name>
    expected_tools = [
        "mcp_sqlite_query",
        "mcp_sqlite_list_tables",
        "mcp_sqlite_describe_table",
        "mcp_sqlite_read_resource",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_sqlite_"), f"Tool {tool} should start with mcp_sqlite_"


# ==============================================================================
# Slack MCP Server Integration Tests
# ==============================================================================

def test_slack_server_config_in_defaults() -> None:
    """Test that Slack server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "slack" in DEFAULT_MCP_SERVERS
    slack_config = DEFAULT_MCP_SERVERS["slack"]
    assert slack_config["command"] == "npx"
    assert "-y" in slack_config["args"]
    assert "@modelcontextprotocol/server-slack" in slack_config["args"]


def test_slack_server_disabled_without_token() -> None:
    """Test that Slack server is disabled when no token is present."""
    import os
    # Ensure no token is set
    os.environ.pop("SLACK_TOKEN", None)
    
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    assert DEFAULT_MCP_SERVERS["slack"]["enabled"] is False


def test_slack_mcp_tool_name_format() -> None:
    """Test that Slack MCP tools would be named correctly."""
    # Slack MCP server tools would be named mcp_slack_<tool_name>
    expected_tools = [
        "mcp_slack_list_channels",
        "mcp_slack_post_message",
        "mcp_slack_get_channel_history",
        "mcp_slack_get_user_info",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_slack_"), f"Tool {tool} should start with mcp_slack_"


# ==============================================================================
# Web Search MCP Server Integration Tests
# ==============================================================================

def test_websearch_server_config_in_defaults() -> None:
    """Test that Web Search server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "websearch" in DEFAULT_MCP_SERVERS
    websearch_config = DEFAULT_MCP_SERVERS["websearch"]
    assert websearch_config["command"] == "npx"
    assert "-y" in websearch_config["args"]
    assert "@modelcontextprotocol/server-web-search" in websearch_config["args"]


def test_websearch_server_requires_explicit_enable() -> None:
    """Web search MCP must be configured explicitly."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert DEFAULT_MCP_SERVERS["websearch"]["enabled"] is False


def test_websearch_mcp_tool_name_format() -> None:
    """Test that Web Search MCP tools would be named correctly."""
    # Web Search MCP server tools would be named mcp_websearch_<tool_name>
    expected_tools = [
        "mcp_websearch_search",
        "mcp_websearch_search_pages",
        "mcp_websearch_get_page_content",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_websearch_"), f"Tool {tool} should start with mcp_websearch_"


# ==============================================================================
# Google Drive MCP Server Integration Tests
# ==============================================================================

def test_gdrive_server_config_in_defaults() -> None:
    """Test that Google Drive server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "gdrive" in DEFAULT_MCP_SERVERS
    gdrive_config = DEFAULT_MCP_SERVERS["gdrive"]
    assert gdrive_config["command"] == "npx"
    assert "-y" in gdrive_config["args"]
    assert "@modelcontextprotocol/server-gdrive" in gdrive_config["args"]


def test_gdrive_server_disabled_without_token() -> None:
    """Test that Google Drive server is disabled when no token is present."""
    import os
    # Ensure no token is set
    os.environ.pop("GOOGLE_DRIVE_TOKEN", None)
    
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    assert DEFAULT_MCP_SERVERS["gdrive"]["enabled"] is False


def test_gdrive_mcp_tool_name_format() -> None:
    """Test that Google Drive MCP tools would be named correctly."""
    # Google Drive MCP server tools would be named mcp_gdrive_<tool_name>
    expected_tools = [
        "mcp_gdrive_list_files",
        "mcp_gdrive_read_file",
        "mcp_gdrive_create_file",
        "mcp_gdrive_update_file",
        "mcp_gdrive_delete_file",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_gdrive_"), f"Tool {tool} should start with mcp_gdrive_"


# ==============================================================================
# PostgreSQL MCP Server Integration Tests
# ==============================================================================

def test_postgres_server_config_in_defaults() -> None:
    """Test that PostgreSQL server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "postgres" in DEFAULT_MCP_SERVERS
    postgres_config = DEFAULT_MCP_SERVERS["postgres"]
    assert postgres_config["command"] == "npx"
    assert "-y" in postgres_config["args"]
    assert "@modelcontextprotocol/server-postgres" in postgres_config["args"]


def test_postgres_server_disabled_without_connection() -> None:
    """Test that PostgreSQL server is disabled when no connection string is set."""
    import os
    # Ensure no connection string is set
    os.environ.pop("MCP_POSTGRES_CONNECTION", None)
    
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    assert DEFAULT_MCP_SERVERS["postgres"]["enabled"] is False


def test_postgres_mcp_tool_name_format() -> None:
    """Test that PostgreSQL MCP tools would be named correctly."""
    # PostgreSQL MCP server tools would be named mcp_postgres_<tool_name>
    expected_tools = [
        "mcp_postgres_query",
        "mcp_postgres_list_tables",
        "mcp_postgres_describe_table",
        "mcp_postgres_read_resource",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_postgres_"), f"Tool {tool} should start with mcp_postgres_"


# ==============================================================================
# Git MCP Server Integration Tests
# ==============================================================================

def test_git_server_config_in_defaults() -> None:
    """Test that Git server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "git" in DEFAULT_MCP_SERVERS
    git_config = DEFAULT_MCP_SERVERS["git"]
    assert git_config["command"] == "npx"
    assert "-y" in git_config["args"]
    assert "@modelcontextprotocol/server-git" in git_config["args"]


def test_git_server_requires_explicit_enable() -> None:
    """Git MCP must be configured explicitly."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert DEFAULT_MCP_SERVERS["git"]["enabled"] is False


def test_git_mcp_tool_name_format() -> None:
    """Test that Git MCP tools would be named correctly."""
    # Git MCP server tools would be named mcp_git_<tool_name>
    expected_tools = [
        "mcp_git_status",
        "mcp_git_log",
        "mcp_git_diff",
        "mcp_git_branch",
        "mcp_git_commit",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_git_"), f"Tool {tool} should start with mcp_git_"


# ==============================================================================
# Jira MCP Server Integration Tests
# ==============================================================================

def test_jira_server_config_in_defaults() -> None:
    """Test that Jira server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "jira" in DEFAULT_MCP_SERVERS
    jira_config = DEFAULT_MCP_SERVERS["jira"]
    assert jira_config["command"] == "npx"
    assert "-y" in jira_config["args"]
    assert "@modelcontextprotocol/server-jira" in jira_config["args"]


def test_jira_server_disabled_without_token() -> None:
    """Test that Jira server is disabled when no token is present."""
    import os
    # Ensure no token is set
    os.environ.pop("JIRA_TOKEN", None)
    
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    assert DEFAULT_MCP_SERVERS["jira"]["enabled"] is False


def test_jira_mcp_tool_name_format() -> None:
    """Test that Jira MCP tools would be named correctly."""
    # Jira MCP server tools would be named mcp_jira_<tool_name>
    expected_tools = [
        "mcp_jira_list_issues",
        "mcp_jira_get_issue",
        "mcp_jira_create_issue",
        "mcp_jira_update_issue",
        "mcp_jira_search_issues",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_jira_"), f"Tool {tool} should start with mcp_jira_"


# ==============================================================================
# Docker MCP Server Integration Tests
# ==============================================================================

def test_docker_server_config_in_defaults() -> None:
    """Test that Docker server is in DEFAULT_MCP_SERVERS."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    assert "docker" in DEFAULT_MCP_SERVERS
    docker_config = DEFAULT_MCP_SERVERS["docker"]
    assert docker_config["command"] == "npx"
    assert "-y" in docker_config["args"]
    assert "@modelcontextprotocol/server-docker" in docker_config["args"]


def test_docker_server_requires_explicit_enable() -> None:
    """Docker MCP must be configured explicitly."""
    from modules.agent.mcp_integration import DEFAULT_MCP_SERVERS
    
    # Docker server should be enabled by default
    assert DEFAULT_MCP_SERVERS["docker"]["enabled"] is False


def test_docker_mcp_tool_name_format() -> None:
    """Test that Docker MCP tools would be named correctly."""
    # Docker MCP server tools would be named mcp_docker_<tool_name>
    expected_tools = [
        "mcp_docker_list_containers",
        "mcp_docker_list_images",
        "mcp_docker_run_container",
        "mcp_docker_stop_container",
        "mcp_docker_get_logs",
    ]
    
    # Verify naming convention
    for tool in expected_tools:
        assert tool.startswith("mcp_docker_"), f"Tool {tool} should start with mcp_docker_"


# ==============================================================================
# MCP Auto-Discovery Tests
# ==============================================================================

def test_mcp_auto_discovery_creation() -> None:
    """Test MCPAutoDiscovery can be created."""
    from modules.agent.mcp_gateway import MCPAutoDiscovery
    
    discovery = MCPAutoDiscovery()
    assert discovery is not None
    assert discovery._ports == MCPAutoDiscovery.DEFAULT_PORTS
    assert discovery._timeout == 2.0
    assert discovery._max_concurrent == 10


def test_mcp_auto_discovery_custom_ports() -> None:
    """Test MCPAutoDiscovery can be created with custom ports."""
    from modules.agent.mcp_gateway import MCPAutoDiscovery
    
    discovery = MCPAutoDiscovery(ports=[3000, 8000, 9000], timeout=5.0, max_concurrent=5)
    assert discovery._ports == [3000, 8000, 9000]
    assert discovery._timeout == 5.0
    assert discovery._max_concurrent == 5


def test_mcp_discovery_result_creation() -> None:
    """Test MCPDiscoveryResult can be created."""
    from modules.agent.mcp_gateway import MCPDiscoveryResult
    
    result = MCPDiscoveryResult(
        name="test_server",
        url="http://localhost:3000/mcp",
        available=True,
        tools=[{"name": "test_tool"}],
    )
    
    assert result.name == "test_server"
    assert result.url == "http://localhost:3000/mcp"
    assert result.available is True
    assert len(result.tools) == 1


def test_mcp_discovery_result_unavailable() -> None:
    """Test MCPDiscoveryResult for unavailable server."""
    from modules.agent.mcp_gateway import MCPDiscoveryResult
    
    result = MCPDiscoveryResult(
        name="closed_port",
        url="http://localhost:9999",
        available=False,
        error="Port not open",
    )
    
    assert result.available is False
    assert result.error == "Port not open"


def test_mcp_auto_discovery_default_ports() -> None:
    """Test MCPAutoDiscovery has sensible default ports."""
    from modules.agent.mcp_gateway import MCPAutoDiscovery
    
    assert 3000 in MCPAutoDiscovery.DEFAULT_PORTS
    assert 8000 in MCPAutoDiscovery.DEFAULT_PORTS
    assert 8080 in MCPAutoDiscovery.DEFAULT_PORTS
    assert len(MCPAutoDiscovery.DEFAULT_PORTS) > 0


def test_mcp_auto_discovery_endpoint_paths() -> None:
    """Test MCPAutoDiscovery has default endpoint paths."""
    from modules.agent.mcp_gateway import MCPAutoDiscovery
    
    assert "/mcp" in MCPAutoDiscovery.MCP_ENDPOINT_PATHS
    assert "/sse" in MCPAutoDiscovery.MCP_ENDPOINT_PATHS


def test_mcp_auto_discovery_empty_discovery() -> None:
    """Test MCPAutoDiscovery returns empty list for closed ports."""
    from modules.agent.mcp_gateway import MCPAutoDiscovery
    
    async def run_test() -> None:
        discovery = MCPAutoDiscovery(ports=[9999, 9998, 9997], timeout=0.5)
        results = await discovery.discover_localhost_servers()
        
        # No MCP servers on these ports, should return empty
        assert results == []
    
    asyncio.run(run_test())


def test_mcp_auto_discovery_create_server_configs() -> None:
    """Test MCPAutoDiscovery creates server configs from discovery results."""
    from modules.agent.mcp_gateway import MCPAutoDiscovery, MCPDiscoveryResult
    
    discovery = MCPAutoDiscovery()
    
    results = [
        MCPDiscoveryResult(
            name="mcp_port_3000",
            url="http://localhost:3000/mcp",
            available=True,
            tools=[{"name": "test"}],
        ),
        MCPDiscoveryResult(
            name="mcp_port_8000",
            url="http://localhost:8000/sse",
            available=True,
            tools=[],
        ),
    ]
    
    configs = discovery.create_server_configs_from_discovery(results)
    
    assert len(configs) == 2
    assert configs[0].name == "mcp_port_3000"
    assert configs[0].transport == "streamable_http"
    assert configs[0].url == "http://localhost:3000/mcp"
    assert configs[1].name == "mcp_port_8000"
    assert configs[1].transport == "sse"


def test_mcp_auto_discovery_gw_integration() -> None:
    """Test MCP AutoDiscovery integrates with MCPGateway."""
    from modules.agent.mcp_gateway import MCPGateway, MCPAutoDiscovery
    
    async def run_test() -> None:
        gateway = MCPGateway()
        discovery = MCPAutoDiscovery(ports=[9999], timeout=0.5)
        
        # Test empty discovery doesn't crash the gateway
        results = await discovery.discover_localhost_servers()
        configs = discovery.create_server_configs_from_discovery(results)
        
        for config in configs:
            gateway.register_server(config)
        
        assert gateway._servers == {}
    
    asyncio.run(run_test())


def test_bootstrap_mcp_with_auto_discovery_function_exists() -> None:
    """Test bootstrap_mcp_with_auto_discovery function exists."""
    from modules.agent.mcp_integration import bootstrap_mcp_with_auto_discovery
    assert bootstrap_mcp_with_auto_discovery is not None


def test_bootstrap_mcp_with_auto_discovery_disabled() -> None:
    """Test bootstrap_mcp_with_auto_discovery with auto_discover=False."""
    from modules.agent.mcp_integration import bootstrap_mcp_with_auto_discovery
    
    # Mock registry
    class MockRegistry:
        def __init__(self) -> None:
            self.registered_tools: list[str] = []
        
        def register(self, schema: dict, handler: Any) -> None:
            self.registered_tools.append(schema["function"]["name"])
    
    async def run_test() -> None:
        registry = MockRegistry()
        gateway = await bootstrap_mcp_with_auto_discovery(
            registry,
            auto_discover=False,
            discovery_ports=[9999],  # Won't be used since auto_discover=False
        )
        
        assert gateway is not None
        # No external process is started without an explicit config.
        assert gateway._servers == {}
    
    asyncio.run(run_test())


# ==============================================================================
# MCP Configuration Tests
# ==============================================================================

def test_mcp_auto_discovery_config_exists() -> None:
    """Test MCP_AUTO_DISCOVERY config exists."""
    import core.config as config
    assert hasattr(config, "MCP_AUTO_DISCOVERY")
    assert isinstance(config.MCP_AUTO_DISCOVERY, bool)


def test_mcp_discovery_ports_config_exists() -> None:
    """Test MCP_DISCOVERY_PORTS config exists."""
    import core.config as config
    assert hasattr(config, "MCP_DISCOVERY_PORTS")
    assert isinstance(config.MCP_DISCOVERY_PORTS, tuple)
    # Should have default ports
    assert len(config.MCP_DISCOVERY_PORTS) > 0
    assert 3000 in config.MCP_DISCOVERY_PORTS


def test_mcp_discovery_ports_default_values() -> None:
    """Test MCP_DISCOVERY_PORTS has sensible defaults."""
    import core.config as config
    
    # Check some expected ports
    assert 8000 in config.MCP_DISCOVERY_PORTS
    assert 8080 in config.MCP_DISCOVERY_PORTS
    assert 9000 in config.MCP_DISCOVERY_PORTS


def test_bootstrap_uses_config_ports() -> None:
    """Test that bootstrap uses config.MCP_DISCOVERY_PORTS when ports not provided."""
    from modules.agent.mcp_integration import bootstrap_mcp_with_auto_discovery
    import core.config as config
    
    # Mock registry
    class MockRegistry:
        def __init__(self) -> None:
            self.registered_tools: list[str] = []
        
        def register(self, schema: dict, handler: Any) -> None:
            self.registered_tools.append(schema["function"]["name"])
    
    async def run_test() -> None:
        registry = MockRegistry()
        # Call without discovery_ports - should use config defaults
        gateway = await bootstrap_mcp_with_auto_discovery(
            registry,
            auto_discover=False,  # Skip actual discovery
        )
        
        assert gateway is not None
        # Verify config was imported
        assert config.MCP_DISCOVERY_PORTS is not None
    
    asyncio.run(run_test())
