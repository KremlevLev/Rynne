# modules/agent/mcp_integration.py
"""MCP Integration Bootstrap.

Connects MCP servers and registers their tools with the existing tool registry.
Supports environment-based configuration for tokens and database paths.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from modules.agent.mcp_gateway import MCPGateway, MCPServerConfig

logger = logging.getLogger("MCPIntegration")


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_bundled_telegram_server_config(
    *,
    project_root: Path | None = None,
    python_executable: str | None = None,
) -> MCPServerConfig | None:
    """Build the opt-in Telegram MCP config without exposing secrets as tools."""
    if not _env_flag("NOVA_TELEGRAM_MCP_ENABLED"):
        return None
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id.isdigit() or not api_hash:
        logger.warning(
            "Telegram MCP is enabled but credentials are missing. "
            "Run scripts/setup_telegram_mcp.py."
        )
        return None
    packaged = bool(getattr(sys, "frozen", False)) and python_executable is None
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    server_path = root / "integrations" / "telegram_mcp" / "server.py"
    if not packaged and not server_path.is_file():
        logger.warning("Bundled Telegram MCP server is missing: %s", server_path)
        return None
    env = {
        "TELEGRAM_API_ID": api_id,
        "TELEGRAM_API_HASH": api_hash,
    }
    session_path = os.environ.get("TELEGRAM_SESSION_PATH", "").strip()
    if session_path:
        env["TELEGRAM_SESSION_PATH"] = session_path
    executable = python_executable or sys.executable
    return MCPServerConfig(
        name="telegram",
        command=executable,
        args=["--telegram-mcp-server"] if packaged else [str(server_path)],
        env=env,
        enabled=True,
        transport="stdio",
        timeout=45.0,
    )


def create_bundled_telegram_bot_server_config(
    *,
    project_root: Path | None = None,
    python_executable: str | None = None,
) -> MCPServerConfig | None:
    """Build the official Bot API/Telegram Business MCP configuration."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or ":" not in token:
        return None
    packaged = bool(getattr(sys, "frozen", False)) and python_executable is None
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    server_path = root / "integrations" / "telegram_bot_mcp" / "server.py"
    if not packaged and not server_path.is_file():
        logger.warning("Bundled Telegram Business MCP server is missing: %s", server_path)
        return None
    env = {"TELEGRAM_BOT_TOKEN": token}
    control_user_ids = os.environ.get("TELEGRAM_CONTROL_USER_IDS", "").strip()
    if control_user_ids:
        env["TELEGRAM_CONTROL_USER_IDS"] = control_user_ids
    store_path = os.environ.get("TELEGRAM_BOT_STORE_PATH", "").strip()
    if store_path:
        env["TELEGRAM_BOT_STORE_PATH"] = store_path
    executable = python_executable or sys.executable
    return MCPServerConfig(
        name="telegram_business",
        command=executable,
        args=["--telegram-bot-mcp-server"] if packaged else [str(server_path)],
        env=env,
        enabled=True,
        transport="stdio",
        timeout=45.0,
    )


def _resolve_env_references(
    values: dict[str, Any],
) -> dict[str, str]:
    """Разворачивает только явные ``${ENV_NAME}``, не читая секреты моделью."""
    resolved: dict[str, str] = {}
    for key, raw_value in values.items():
        value = str(raw_value)
        match = re.fullmatch(
            r"\$\{([A-Z][A-Z0-9_]*)\}",
            value,
        )
        resolved[str(key)] = (
            os.environ.get(match.group(1), "")
            if match
            else value
        )
    return resolved


def load_mcp_config(
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Загружает явный MCP config в Claude/Codex-совместимом формате.

    Автоматически исполнять выдуманный список npm-пакетов опасно, поэтому
    Nova подключает только серверы из NOVA_MCP_CONFIG (или переданного пути).
    """
    raw_path = (
        str(config_path)
        if config_path is not None
        else os.environ.get("NOVA_MCP_CONFIG", "")
    )
    if not raw_path:
        return {}

    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        logger.warning(
            "MCP config does not exist: %s",
            path,
        )
        return {}

    try:
        loaded = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to load MCP config %s: %s",
            path,
            exc,
        )
        return {}

    if not isinstance(loaded, dict):
        logger.warning(
            "MCP config root must be an object: %s",
            path,
        )
        return {}
    return loaded


def _get_env_tokens() -> dict[str, str]:
    """Load MCP server tokens from environment variables."""
    return {
        "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
        "SLACK_TOKEN": os.environ.get("SLACK_TOKEN", ""),
        "GOOGLE_DRIVE_TOKEN": os.environ.get("GOOGLE_DRIVE_TOKEN", ""),
        "JIRA_TOKEN": os.environ.get("JIRA_TOKEN", ""),
    }


def _get_sqlite_path() -> str:
    """Get SQLite database path from environment."""
    return os.environ.get("MCP_SQLITE_PATH", "nova_memory.db")


def _get_postgres_connection_string() -> str:
    """Get PostgreSQL connection string from environment."""
    return os.environ.get("MCP_POSTGRES_CONNECTION", "")


async def initialize_mcp_servers(
    gateway: MCPGateway,
    registry: Any,
    *,
    auto_discover: bool = False,
) -> int:
    """
    Initialize MCP servers and register their tools.
    
    Args:
        gateway: MCPGateway instance
        registry: ToolRegistry to register tools with
        auto_discover: If True, discover localhost MCP servers
        
    Returns:
        Number of MCP tools registered
    """
    # Initialize the gateway to discover tools
    result = await gateway.initialize()
    logger.info("MCP initialization: %s", result.message)
    
    # Register MCP tools with the registry
    count = await gateway.register_with_registry(registry)
    logger.info("Registered %d MCP tools with registry", count)
    
    return count


def create_mcp_gateway_from_config(config: dict[str, Any]) -> MCPGateway:
    """
    Create MCP Gateway from configuration dict.
    
    Expected config format:
    {
        "mcp": {
            "github": {
                "command": "node",
                "args": ["@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "token"}
            }
        }
    }
    """
    gateway = MCPGateway()
    
    mcp_config = (
        config.get("mcpServers")
        or config.get("mcp")
        or {}
    )

    if not isinstance(mcp_config, dict):
        logger.warning("MCP server config must be an object.")
        return gateway
    
    for name, server_config in mcp_config.items():
        try:
            config_obj = MCPServerConfig(
                name=name,
                command=server_config.get("command", ""),
                args=[
                    str(argument)
                    for argument
                    in server_config.get("args", [])
                ],
                env=_resolve_env_references(
                    server_config.get("env", {})
                ),
                enabled=server_config.get("enabled", True),
                transport=server_config.get(
                    "transport",
                    (
                        "streamable_http"
                        if server_config.get("url")
                        else "stdio"
                    ),
                ),
                url=str(server_config.get("url", "")),
                timeout=float(
                    server_config.get("timeout", 30.0)
                ),
            )
            gateway.register_server(config_obj)
        except Exception as exc:
            logger.warning(
                "Failed to register MCP server %s: %s",
                name,
                exc,
            )
    
    return gateway


# Legacy templates kept for config migration only. Main bootstrap never starts
# them automatically: package names and trust must be verified by the user.
DEFAULT_MCP_SERVERS: dict[str, dict[str, Any]] = {
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {},  # Will be populated from GITHUB_TOKEN env var
        "enabled": False,  # Will be True if GITHUB_TOKEN is available
    },
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "--directory", "."],
        "env": {},
        "enabled": False,
    },
    "sqlite": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite"],
        "env": {},
        "enabled": False,  # Will be True if MCP_SQLITE_PATH is set
    },
    "slack": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env": {},  # Will be populated from SLACK_TOKEN env var
        "enabled": False,  # Will be True if SLACK_TOKEN is available
    },
    "websearch": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-web-search"],
        "env": {},  # No token required for basic web search
        "enabled": False,
    },
    "gdrive": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gdrive"],
        "env": {},  # Will be populated from GOOGLE_DRIVE_TOKEN env var
        "enabled": False,  # Will be True if GOOGLE_DRIVE_TOKEN is available
    },
    "postgres": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres"],
        "env": {},  # Will be populated from MCP_POSTGRES_CONNECTION env var
        "enabled": False,  # Will be True if MCP_POSTGRES_CONNECTION is set
    },
    "git": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-git"],
        "env": {},  # No token required for local git operations
        "enabled": False,
    },
    "jira": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-jira"],
        "env": {},  # Will be populated from JIRA_TOKEN env var
        "enabled": False,  # Will be True if JIRA_TOKEN is available
    },
    "docker": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-docker"],
        "env": {},  # No token required for local Docker operations
        "enabled": False,
    },
}


async def bootstrap_mcp_from_defaults(
    registry: Any,
) -> MCPGateway:
    """
    Legacy helper for users who explicitly choose bundled templates.

    The normal Nova bootstrap uses NOVA_MCP_CONFIG and does not call this
    function, because package names and permissions require a separate audit.
    """
    gateway = MCPGateway()
    env_tokens = _get_env_tokens()
    sqlite_path = _get_sqlite_path()
    postgres_conn = _get_postgres_connection_string()
    
    for name, server_config in DEFAULT_MCP_SERVERS.items():
        # Determine if server should be enabled
        should_enable = server_config.get("enabled", False)
        
        # Override based on environment tokens
        if name == "github" and env_tokens.get("GITHUB_TOKEN"):
            should_enable = True
        elif name == "slack" and env_tokens.get("SLACK_TOKEN"):
            should_enable = True
        elif name == "sqlite" and os.environ.get("MCP_SQLITE_PATH"):
            should_enable = True
        elif name == "gdrive" and env_tokens.get("GOOGLE_DRIVE_TOKEN"):
            should_enable = True
        elif name == "postgres" and postgres_conn:
            should_enable = True
        elif name == "jira" and env_tokens.get("JIRA_TOKEN"):
            should_enable = True
        
        if should_enable:
            # Build env dict from server config + environment tokens
            env = {}
            if name == "github" and env_tokens.get("GITHUB_TOKEN"):
                env["GITHUB_TOKEN"] = env_tokens["GITHUB_TOKEN"]
            if name == "slack" and env_tokens.get("SLACK_TOKEN"):
                env["SLACK_TOKEN"] = env_tokens["SLACK_TOKEN"]
            if name == "gdrive" and env_tokens.get("GOOGLE_DRIVE_TOKEN"):
                env["GOOGLE_DRIVE_TOKEN"] = env_tokens["GOOGLE_DRIVE_TOKEN"]
            if name == "postgres" and postgres_conn:
                env["MCP_POSTGRES_CONNECTION"] = postgres_conn
            if name == "jira" and env_tokens.get("JIRA_TOKEN"):
                env["JIRA_TOKEN"] = env_tokens["JIRA_TOKEN"]
            
            # Build args for SQLite with path
            args = server_config["args"].copy()
            if name == "sqlite" and os.environ.get("MCP_SQLITE_PATH"):
                # Add --db-path argument for SQLite server
                args.extend(["--db-path", sqlite_path])
            
            # Merge with any existing env from config
            env.update(server_config.get("env", {}))
            
            config_obj = MCPServerConfig(
                name=name,
                command=server_config["command"],
                args=args,
                env=env,
                enabled=True,
            )
            gateway.register_server(config_obj)
            logger.info(
                "MCP server '%s' enabled with env token: %s",
                name,
                "yes" if env else "no",
            )
    
    await gateway.initialize()
    await gateway.register_with_registry(registry)
    
    return gateway


async def bootstrap_mcp_with_auto_discovery(
    registry: Any,
    auto_discover: bool | None = None,
    discovery_ports: list[int] | None = None,
) -> MCPGateway:
    """
    Bootstrap MCP with default servers and auto-discovery of localhost servers.
    
    This function:
    1. Bootsraps default MCP servers based on environment tokens
    2. Optionally discovers MCP servers running on localhost via SSE
    3. Registers all discovered tools with the registry
    
    Args:
        registry: ToolRegistry to register tools with
        auto_discover: If True, scan localhost for MCP SSE servers.
                      If None, uses NOVA_MCP_AUTO_DISCOVERY from config.
        discovery_ports: Optional list of ports to scan (uses config defaults if None)
        
    Returns:
        Configured MCPGateway instance
    """
    import core.config as config
    
    # Use config value if not explicitly provided
    if auto_discover is None:
        auto_discover = config.MCP_AUTO_DISCOVERY
    
    # Use config ports if not explicitly provided
    ports = discovery_ports or list(config.MCP_DISCOVERY_PORTS)
    
    gateway = MCPGateway()
    
    # Подключаем только явно заданные пользователем серверы. Старый код
    # запускал несколько непроверенных npx-пакетов при каждом старте Nova.
    configured_gateway = create_mcp_gateway_from_config(
        load_mcp_config()
    )
    for server_config in configured_gateway._servers.values():
        gateway.register_server(server_config)

    telegram_config = create_bundled_telegram_server_config()
    if telegram_config is not None and telegram_config.name not in gateway._servers:
        gateway.register_server(telegram_config)

    telegram_bot_config = create_bundled_telegram_bot_server_config()
    if telegram_bot_config is not None and telegram_bot_config.name not in gateway._servers:
        gateway.register_server(telegram_bot_config)
    
    # Auto-discover localhost MCP servers (SSE transport)
    if auto_discover:
        from modules.agent.mcp_gateway import MCPAutoDiscovery
        
        discovery = MCPAutoDiscovery(ports=ports)
        try:
            discovered_servers = await discovery.discover_localhost_servers()
            
            for server in discovered_servers:
                # Create unique name if conflict exists
                server_name = server.name
                original_name = server_name
                counter = 1
                while server_name in gateway._servers:
                    server_name = f"{original_name}_{counter}"
                    counter += 1
                
                config = MCPServerConfig(
                    name=server_name,
                    command="",
                    transport=(
                        "sse"
                        if server.url.rstrip("/").endswith("/sse")
                        else "streamable_http"
                    ),
                    url=server.url,
                    enabled=True,
                )
                gateway.register_server(config)
                logger.info(
                    "Auto-discovered MCP server at %s with %d tools",
                    server.url,
                    len(server.tools),
                )
        except Exception as exc:
            logger.warning("Auto-discovery of localhost MCP servers failed: %s", exc)
    
    await gateway.initialize()
    await gateway.register_with_registry(registry)
    
    return gateway
