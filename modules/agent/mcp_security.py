# modules/agent/mcp_security.py
"""MCP Security Middleware for safe tool execution.

Provides:
- Sandbox for unknown MCP servers
- Command allowlist for server startup
- Per-server and per-tool permissions
- Rate limiting and quota accounting
- Tool call audit and redaction
- Health score tracking
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from modules.domain.results import ToolResult
from modules.tools.base import RiskLevel, ToolCategory

logger = logging.getLogger("MCPSecurity")


class MCPRiskLevel(IntEnum):
    """Risk levels for MCP tools (mapped to internal RiskLevel)."""
    READ_ONLY = 1
    LOW = 2
    WRITE = 3
    EXECUTE = 4
    DESTRUCTIVE = 5
    CRITICAL = 6


# Default allowlist of safe MCP server commands
DEFAULT_MCP_ALLOWLIST: set[str] = {
    # Official MCP servers
    "@modelcontextprotocol/server-filesystem",
    "@modelcontextprotocol/server-sqlite",
    "@modelcontextprotocol/server-git",
    "@modelcontextprotocol/server-github",
    "@modelcontextprotocol/server-slack",
    "@modelcontextprotocol/server-web-search",
    "@modelcontextprotocol/server-gdrive",
    "@modelcontextprotocol/server-postgres",
    "@modelcontextprotocol/server-jira",
    "@modelcontextprotocol/server-docker",
    # Common safe patterns
    "python",
    "python3",
    "node",
    "npx",
}

# Dangerous patterns that should never be allowed
DANGEROUS_PATTERNS: list[str] = [
    r"rm\s+-rf",
    r"sudo",
    r"chmod\s+777",
    r":()\s*{\s*:\|:&\s*}",  # Fork bomb
    r">\s*/dev/sd",
    r"mkfs",
    r"dd\s+if=",
    r"curl.*\|\s*bash",
    r"wget.*\|\s*bash",
]


@dataclass
class MCPServerSecurityConfig:
    """Security configuration for an MCP server."""
    name: str
    allow_network: bool = False
    allow_filesystem: bool = False
    allowed_paths: list[str] = field(default_factory=list)
    rate_limit_per_minute: int = 60
    max_concurrent_calls: int = 5
    read_only_mode: bool = False
    trust_level: int = 50  # 0-100, 100 = fully trusted


@dataclass
class MCPToolSecurityInfo:
    """Security metadata for an MCP tool."""
    tool_name: str
    server_name: str
    risk: RiskLevel
    category: ToolCategory
    requires_confirmation: bool = False
    audit_redact: list[str] = field(default_factory=list)  # Keys to redact in logs


class MCPSecurityMiddleware:
    """
    Security middleware for MCP tool calls.
    
    Provides:
    - Command allowlist validation
    - Per-server security policies
    - Rate limiting
    - Audit logging with redaction
    - Health score tracking
    """
    
    def __init__(
        self,
        allowlist: set[str] | None = None,
        default_rate_limit: int = 60,
    ) -> None:
        self._allowlist = allowlist or DEFAULT_MCP_ALLOWLIST
        self._server_configs: dict[str, MCPServerSecurityConfig] = {}
        self._tool_security: dict[str, MCPToolSecurityInfo] = {}
        self._rate_limits: dict[str, list[float]] = {}
        self._health_scores: dict[str, float] = {}
        self._default_rate_limit = default_rate_limit
    
    def register_server(self, config: MCPServerSecurityConfig) -> None:
        """Register security configuration for a server."""
        self._server_configs[config.name] = config
        if config.name not in self._health_scores:
            self._health_scores[config.name] = 100.0
        logger.info("Registered security config for MCP server: %s", config.name)
    
    def register_tool(self, info: MCPToolSecurityInfo) -> None:
        """Register security metadata for a tool."""
        self._tool_security[info.tool_name] = info
    
    def is_command_allowed(self, command: str, args: list[str]) -> tuple[bool, str]:
        """
        Check if MCP server command is in allowlist.
        
        Returns (allowed, reason) tuple.
        """
        # Check for dangerous patterns
        full_command = f"{command} {' '.join(args)}"
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, full_command, re.IGNORECASE):
                return False, f"Command matches dangerous pattern: {pattern}"
        
        # Check allowlist
        if command in self._allowlist:
            return True, "Command in allowlist"
        
        # Check if any arg is in allowlist (for npx -y @server/package)
        for arg in args:
            if arg in self._allowlist:
                return True, f"Package {arg} in allowlist"
        
        return False, f"Command '{command}' not in allowlist"
    
    def check_rate_limit(self, tool_name: str) -> bool:
        """
        Check if tool call is within rate limit.
        
        Returns True if call is allowed, False if rate limited.
        """
        now = time.time()
        minute_ago = now - 60
        
        # Clean old entries
        if tool_name in self._rate_limits:
            self._rate_limits[tool_name] = [
                t for t in self._rate_limits[tool_name] if t > minute_ago
            ]
        else:
            self._rate_limits[tool_name] = []
        
        # Get rate limit for this tool
        config = self._server_configs.get(tool_name.split("_")[1] if "_" in tool_name else "")
        limit = config.rate_limit_per_minute if config else self._default_rate_limit
        
        # Check limit
        if len(self._rate_limits[tool_name]) >= limit:
            logger.warning("Rate limit exceeded for tool: %s", tool_name)
            return False
        
        self._rate_limits[tool_name].append(now)
        return True
    
    def get_tool_risk(self, tool_name: str) -> RiskLevel:
        """Get risk level for an MCP tool."""
        info = self._tool_security.get(tool_name)
        return info.risk if info else RiskLevel.LOW
    
    def get_tool_category(self, tool_name: str) -> ToolCategory:
        """Get category for an MCP tool."""
        info = self._tool_security.get(tool_name)
        return info.category if info else ToolCategory.UNKNOWN
    
    def requires_confirmation(self, tool_name: str) -> bool:
        """Check if tool requires user confirmation."""
        info = self._tool_security.get(tool_name)
        return info.requires_confirmation if info else False
    
    def redact_sensitive_data(
        self,
        tool_name: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Redact sensitive data from tool result for logging."""
        info = self._tool_security.get(tool_name)
        if not info or not info.audit_redact:
            return result
        
        redacted = result.copy()
        for key in info.audit_redact:
            if key in redacted:
                redacted[key] = "[REDACTED]"
        
        return redacted
    
    def get_health_score(self, server_name: str) -> float:
        """Get health score for a server (0-100)."""
        return self._health_scores.get(server_name, 100.0)
    
    def update_health_score(
        self,
        server_name: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Update health score based on tool call result."""
        current = self._health_scores.get(server_name, 100.0)
        
        if success:
            # Gradually recover health on success
            current = min(100.0, current + 1.0)
        else:
            # Drop health on failure
            current = max(0.0, current - 5.0)
        
        self._health_scores[server_name] = current
        
        if current < 30:
            logger.warning(
                "MCP server %s health score low: %.1f - consider disabling",
                server_name,
                current,
            )
    
    def is_server_healthy(self, server_name: str, threshold: float = 30.0) -> bool:
        """Check if server is healthy enough to use."""
        return self.get_health_score(server_name) >= threshold
    
    def get_server_config(self, server_name: str) -> MCPServerSecurityConfig | None:
        """Get security config for a server."""
        return self._server_configs.get(server_name)
    
    def set_read_only_mode(self, server_name: str, enabled: bool) -> None:
        """Set read-only mode for a server."""
        if server_name in self._server_configs:
            self._server_configs[server_name].read_only_mode = enabled
        else:
            self._server_configs[server_name] = MCPServerSecurityConfig(
                name=server_name,
                read_only_mode=enabled,
            )
    
    def is_read_only(self, tool_name: str) -> bool:
        """Check if tool is in read-only mode."""
        server_name = tool_name.split("_")[1] if "_" in tool_name else ""
        config = self._server_configs.get(server_name)
        return config.read_only_mode if config else False


def infer_mcp_tool_risk(tool_name: str, description: str = "") -> RiskLevel:
    """Infer risk level from tool name and description."""
    lowered = f"{tool_name} {description}".lower()
    
    # Check for destructive operations
    if any(word in lowered for word in ["delete", "remove", "drop", "kill", "stop"]):
        return RiskLevel.DESTRUCTIVE
    
    if any(word in lowered for word in ["write", "create", "update", "modify", "edit"]):
        return RiskLevel.WRITE
    
    # Sending data to a person/service is an external side effect. Classify it
    # as execute so Nova's permission layer must obtain explicit confirmation.
    if any(word in lowered for word in [
        "execute", "run", "command", "shell", "bash",
        "send", "reply", "publish", "post_message",
    ]):
        return RiskLevel.EXECUTE
    
    if any(word in lowered for word in ["read", "get", "list", "search", "query"]):
        return RiskLevel.READ_ONLY
    
    return RiskLevel.LOW


def infer_mcp_tool_category(tool_name: str, description: str = "") -> ToolCategory:
    """Infer category from tool name and description."""
    lowered = f"{tool_name} {description}".lower()

    if any(word in lowered for word in [
        "send", "reply", "publish", "post_message",
    ]):
        return ToolCategory.NETWORK_WRITE

    if any(word in lowered for word in ["telegram", "message", "chat"]):
        return ToolCategory.WEB_READ
    
    if any(word in lowered for word in ["file", "read", "write", "path"]):
        return ToolCategory.FILE_READ if "read" in lowered else ToolCategory.FILE_WRITE
    
    if any(word in lowered for word in ["web", "http", "url", "fetch"]):
        return ToolCategory.WEB_READ
    
    if any(word in lowered for word in ["database", "sql", "query"]):
        return ToolCategory.SYSTEM_READ
    
    if any(word in lowered for word in ["git", "github", "repo"]):
        return ToolCategory.DEVELOPMENT
    
    if any(word in lowered for word in ["docker", "container"]):
        return ToolCategory.SYSTEM_READ
    
    return ToolCategory.UNKNOWN


# Global security middleware instance
_security_middleware: MCPSecurityMiddleware | None = None


def get_mcp_security() -> MCPSecurityMiddleware:
    """Get global MCP security middleware instance."""
    global _security_middleware
    if _security_middleware is None:
        _security_middleware = MCPSecurityMiddleware()
    return _security_middleware
