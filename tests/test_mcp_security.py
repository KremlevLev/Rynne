# tests/test_mcp_security.py
"""Tests for MCP Security Middleware."""
from __future__ import annotations

import pytest

from modules.agent.mcp_security import (
    MCPSecurityMiddleware,
    MCPServerSecurityConfig,
    MCPToolSecurityInfo,
    infer_mcp_tool_risk,
    infer_mcp_tool_category,
    DEFAULT_MCP_ALLOWLIST,
    DANGEROUS_PATTERNS,
)
from modules.tools.base import RiskLevel, ToolCategory


class TestMCPSecurityMiddleware:
    """Tests for MCPSecurityMiddleware class."""

    def test_init_default_allowlist(self) -> None:
        """Test initialization with default allowlist."""
        security = MCPSecurityMiddleware()
        assert security._allowlist == DEFAULT_MCP_ALLOWLIST

    def test_init_custom_allowlist(self) -> None:
        """Test initialization with custom allowlist."""
        custom = {"custom-server"}
        security = MCPSecurityMiddleware(allowlist=custom)
        assert security._allowlist == custom

    def test_register_server(self) -> None:
        """Test server registration."""
        security = MCPSecurityMiddleware()
        config = MCPServerSecurityConfig(
            name="test_server",
            rate_limit_per_minute=30,
        )
        security.register_server(config)
        
        assert "test_server" in security._server_configs
        assert security.get_health_score("test_server") == 100.0

    def test_register_tool(self) -> None:
        """Test tool security registration."""
        security = MCPSecurityMiddleware()
        info = MCPToolSecurityInfo(
            tool_name="mcp_test_read",
            server_name="test",
            risk=RiskLevel.READ_ONLY,
            category=ToolCategory.SYSTEM_READ,
        )
        security.register_tool(info)
        
        assert "mcp_test_read" in security._tool_security
        assert security.get_tool_risk("mcp_test_read") == RiskLevel.READ_ONLY

    def test_is_command_allowed_npx(self) -> None:
        """Test that npx is allowed for known packages."""
        security = MCPSecurityMiddleware()
        
        allowed, reason = security.is_command_allowed(
            "npx",
            ["-y", "@modelcontextprotocol/server-filesystem", "."],
        )
        assert allowed is True
        assert "allowlist" in reason.lower()

    def test_is_command_allowed_dangerous_pattern(self) -> None:
        """Test that dangerous patterns are blocked."""
        security = MCPSecurityMiddleware()
        
        # Test rm -rf pattern
        allowed, reason = security.is_command_allowed(
            "bash",
            ["-c", "rm -rf /"],
        )
        assert allowed is False
        assert "dangerous" in reason.lower()

    def test_is_command_allowed_not_in_allowlist(self) -> None:
        """Test that unknown commands are blocked."""
        security = MCPSecurityMiddleware()
        
        allowed, reason = security.is_command_allowed(
            "unknown_command",
            [],
        )
        assert allowed is False
        assert "not in allowlist" in reason.lower()

    def test_check_rate_limit_allows(self) -> None:
        """Test rate limiting allows calls under limit."""
        security = MCPSecurityMiddleware()
        
        # Should allow first 60 calls
        for i in range(50):
            assert security.check_rate_limit("test_tool") is True

    def test_check_rate_limit_blocks(self) -> None:
        """Test rate limiting blocks calls over limit."""
        security = MCPSecurityMiddleware(default_rate_limit=5)
        
        # Should allow first 5 calls
        for i in range(5):
            assert security.check_rate_limit("test_tool") is True
        
        # Should block 6th call
        assert security.check_rate_limit("test_tool") is False

    def test_get_tool_risk_default(self) -> None:
        """Test default risk level for unknown tools."""
        security = MCPSecurityMiddleware()
        
        assert security.get_tool_risk("unknown_tool") == RiskLevel.LOW

    def test_get_tool_category_default(self) -> None:
        """Test default category for unknown tools."""
        security = MCPSecurityMiddleware()
        
        assert security.get_tool_category("unknown_tool") == ToolCategory.UNKNOWN

    def test_requires_confirmation_default(self) -> None:
        """Test default confirmation requirement."""
        security = MCPSecurityMiddleware()
        
        assert security.requires_confirmation("unknown_tool") is False

    def test_redact_sensitive_data(self) -> None:
        """Test sensitive data redaction."""
        security = MCPSecurityMiddleware()
        info = MCPToolSecurityInfo(
            tool_name="mcp_test_tool",
            server_name="test",
            risk=RiskLevel.LOW,
            category=ToolCategory.UNKNOWN,
            audit_redact=["password", "token", "api_key"],
        )
        security.register_tool(info)
        
        result = {
            "data": "public",
            "password": "secret123",
            "token": "abc123",
        }
        
        redacted = security.redact_sensitive_data("mcp_test_tool", result)
        
        assert redacted["data"] == "public"
        assert redacted["password"] == "[REDACTED]"
        assert redacted["token"] == "[REDACTED]"

    def test_update_health_score_success(self) -> None:
        """Test health score increases on success."""
        security = MCPSecurityMiddleware()
        security._health_scores["test_server"] = 50.0
        
        security.update_health_score("test_server", success=True)
        
        assert security.get_health_score("test_server") == 51.0

    def test_update_health_score_failure(self) -> None:
        """Test health score decreases on failure."""
        security = MCPSecurityMiddleware()
        security._health_scores["test_server"] = 50.0
        
        security.update_health_score("test_server", success=False)
        
        assert security.get_health_score("test_server") == 45.0

    def test_is_server_healthy(self) -> None:
        """Test server health check."""
        security = MCPSecurityMiddleware()
        security._health_scores["healthy_server"] = 80.0
        security._health_scores["unhealthy_server"] = 20.0
        
        assert security.is_server_healthy("healthy_server") is True
        assert security.is_server_healthy("unhealthy_server") is False

    def test_set_read_only_mode(self) -> None:
        """Test read-only mode setting."""
        security = MCPSecurityMiddleware()
        
        security.set_read_only_mode("test", True)
        
        # Tool name format: mcp_{server_name}_{tool_name}
        assert security.is_read_only("mcp_test_read") is True

    def test_is_read_only_no_config(self) -> None:
        """Test read-only check for server without config."""
        security = MCPSecurityMiddleware()
        
        assert security.is_read_only("mcp_unknown_tool") is False


class TestInferMCPToolRisk:
    """Tests for infer_mcp_tool_risk function."""

    def test_infer_read_only(self) -> None:
        """Test inference of read-only risk."""
        assert infer_mcp_tool_risk("read_file", "Read a file") == RiskLevel.READ_ONLY
        assert infer_mcp_tool_risk("get_data", "Get data from API") == RiskLevel.READ_ONLY
        assert infer_mcp_tool_risk("list_items", "List all items") == RiskLevel.READ_ONLY

    def test_infer_write(self) -> None:
        """Test inference of write risk."""
        assert infer_mcp_tool_risk("write_file", "Write to file") == RiskLevel.WRITE
        assert infer_mcp_tool_risk("create_item", "Create new item") == RiskLevel.WRITE
        assert infer_mcp_tool_risk("update_record", "Update record") == RiskLevel.WRITE

    def test_infer_execute(self) -> None:
        """Test inference of execute risk."""
        assert infer_mcp_tool_risk("run_command", "Execute command") == RiskLevel.EXECUTE
        assert infer_mcp_tool_risk("shell_exec", "Run shell") == RiskLevel.EXECUTE
        assert infer_mcp_tool_risk("send_message", "Send Telegram message") == RiskLevel.EXECUTE

    def test_infer_destructive(self) -> None:
        """Test inference of destructive risk."""
        assert infer_mcp_tool_risk("delete_file", "Delete a file") == RiskLevel.DESTRUCTIVE
        assert infer_mcp_tool_risk("remove_item", "Remove item") == RiskLevel.DESTRUCTIVE
        assert infer_mcp_tool_risk("drop_table", "Drop database table") == RiskLevel.DESTRUCTIVE

    def test_infer_low_default(self) -> None:
        """Test default low risk."""
        assert infer_mcp_tool_risk("unknown_tool", "Does something") == RiskLevel.LOW


class TestInferMCPToolCategory:
    """Tests for infer_mcp_tool_category function."""

    def test_infer_file_category(self) -> None:
        """Test inference of file category."""
        assert infer_mcp_tool_risk("read_file", "Read file") == RiskLevel.READ_ONLY
        assert infer_mcp_tool_category("read_file", "Read file") == ToolCategory.FILE_READ
        assert infer_mcp_tool_category("write_file", "Write file") == ToolCategory.FILE_WRITE

    def test_infer_web_category(self) -> None:
        """Test inference of web category."""
        assert infer_mcp_tool_category("fetch_url", "Fetch web page") == ToolCategory.WEB_READ
        assert infer_mcp_tool_category("read_messages", "Read Telegram chat") == ToolCategory.WEB_READ

    def test_infer_network_write_category(self) -> None:
        assert infer_mcp_tool_category(
            "send_message", "Send Telegram message"
        ) == ToolCategory.NETWORK_WRITE

    def test_infer_development_category(self) -> None:
        """Test inference of development category."""
        assert infer_mcp_tool_category("git_commit", "Git commit") == ToolCategory.DEVELOPMENT

    def test_infer_unknown_default(self) -> None:
        """Test default unknown category."""
        assert infer_mcp_tool_category("unknown_tool", "Does something") == ToolCategory.UNKNOWN


class TestDangerousPatterns:
    """Tests for dangerous pattern detection."""

    def test_dangerous_patterns_exist(self) -> None:
        """Test that dangerous patterns are defined."""
        assert len(DANGEROUS_PATTERNS) > 0
        assert any("rm" in p for p in DANGEROUS_PATTERNS)
        assert any("sudo" in p for p in DANGEROUS_PATTERNS)

    def test_default_allowlist_exists(self) -> None:
        """Test that default allowlist is defined."""
        assert len(DEFAULT_MCP_ALLOWLIST) > 0
        assert "@modelcontextprotocol/server-filesystem" in DEFAULT_MCP_ALLOWLIST
        assert "npx" in DEFAULT_MCP_ALLOWLIST
