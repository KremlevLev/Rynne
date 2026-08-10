# modules/agent/mcp_gateway.py
"""MCP Gateway for Recovery & Self-healing.

Provides integration with external MCP servers for:
- Automatic rollback via external tools
- Alternative paths discovery and execution
- Graceful degradation capabilities
- Self-diagnostics
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Callable

from modules.domain.results import ToolResult
from modules.agent.mcp_security import (
    MCPSecurityMiddleware,
    MCPServerSecurityConfig,
    MCPToolSecurityInfo,
    infer_mcp_tool_risk,
    infer_mcp_tool_category,
)
from modules.tools.base import RiskLevel, ToolCategory

logger = logging.getLogger("MCPGateway")


def _redact_mcp_error(message: object, config: "MCPServerConfig") -> str:
    """Remove credentials from MCP failures before logs or UI see them."""
    clean = str(message)
    clean = re.sub(
        r"https://api\.telegram\.org/bot[^/\s]+/",
        "https://api.telegram.org/bot[REDACTED]/",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(
        r"\b\d{5,}:[A-Za-z0-9_-]{20,}\b",
        "[REDACTED_TELEGRAM_TOKEN]",
        clean,
    )
    for key, value in config.env.items():
        if (
            value
            and len(value) >= 8
            and any(marker in key.casefold() for marker in ("token", "secret", "api_key"))
        ):
            clean = clean.replace(value, "[REDACTED]")
    return clean


@dataclass(slots=True)
class MCPDiscoveryResult:
    """Result of MCP server discovery probe."""
    name: str
    url: str
    available: bool
    tools: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


class MCPAutoDiscovery:
    """
    Automatic discovery of localhost MCP servers.
    
    Scans common MCP ports for SSE servers and probes endpoints
    to detect MCP-compatible servers.
    """
    
    # Common MCP/SSE ports
    DEFAULT_PORTS = [3000, 3001, 3002, 8000, 8001, 8080, 8081, 8082, 9000, 9001]
    MCP_ENDPOINT_PATHS = ["/mcp", "/sse", "/api/mcp", "/tools"]
    
    def __init__(
        self,
        ports: list[int] | None = None,
        timeout: float = 2.0,
        max_concurrent: int = 10,
    ) -> None:
        self._ports = ports or self.DEFAULT_PORTS
        self._timeout = timeout
        self._max_concurrent = max_concurrent
    
    async def discover_localhost_servers(
        self,
        ports: list[int] | None = None,
    ) -> list[MCPDiscoveryResult]:
        """
        Discover MCP servers running on localhost.
        
        Args:
            ports: Optional list of ports to scan. Uses default ports if not provided.
            
        Returns:
            List of discovery results for each port checked.
        """
        scan_ports = ports or self._ports
        results = []
        
        # Create semaphore for concurrent connections
        semaphore = asyncio.Semaphore(self._max_concurrent)
        
        async def probe_port(port: int) -> MCPDiscoveryResult:
            async with semaphore:
                return await self._probe_port(port)
        
        # Probe all ports concurrently
        tasks = [probe_port(port) for port in scan_ports]
        results = await asyncio.gather(*tasks)
        
        return [r for r in results if r.available]
    
    async def _probe_port(self, port: int) -> MCPDiscoveryResult:
        """Probe a single port for MCP servers."""
        # First check if port is open
        if not await self._is_port_open(port):
            return MCPDiscoveryResult(
                name=f"port_{port}",
                url=f"http://localhost:{port}",
                available=False,
                error="Port not open",
            )
        
        # Try MCP endpoints
        for path in self.MCP_ENDPOINT_PATHS:
            result = await self._probe_mcp_endpoint(port, path)
            if result.available:
                return result
        
        return MCPDiscoveryResult(
            name=f"port_{port}",
            url=f"http://localhost:{port}",
            available=False,
            error="No MCP endpoint found",
        )
    
    async def _is_port_open(self, port: int) -> bool:
        """Check if a port is open on localhost."""
        try:
            # Use asyncio for non-blocking socket check
            loop = asyncio.get_event_loop()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self._timeout)
            
            result = await loop.run_in_executor(
                None,
                lambda: sock.connect_ex(('localhost', port)) == 0,
            )
            sock.close()
            return result
        except Exception:
            return False
    
    async def _probe_mcp_endpoint(
        self,
        port: int,
        path: str,
    ) -> MCPDiscoveryResult:
        """Probe an MCP endpoint for compatibility."""
        url = f"http://localhost:{port}{path}"
        transport = (
            "sse"
            if path.rstrip("/").endswith("/sse")
            else "streamable_http"
        )
        gateway = MCPGateway(max_retries=1)
        config = MCPServerConfig(
            name=f"mcp_port_{port}",
            command="",
            transport=transport,
            url=url,
            enabled=True,
            timeout=self._timeout,
        )
        gateway.register_server(config)

        try:
            tools = await asyncio.wait_for(
                gateway._discover_tools(config),
                timeout=self._timeout,
            )
            return MCPDiscoveryResult(
                name=f"mcp_port_{port}",
                url=url,
                available=True,
                tools=tools,
            )
        except Exception:
            logger.debug(
                "No MCP server at %s.",
                url,
            )
        finally:
            await gateway.close()

        return MCPDiscoveryResult(
            name=f"port_{port}",
            url=url,
            available=False,
            error="Not MCP-compatible",
        )
    
    def create_server_configs_from_discovery(
        self,
        discovery_results: list[MCPDiscoveryResult],
    ) -> list[MCPServerConfig]:
        """
        Create MCPServerConfig objects from discovery results.
        
        Args:
            discovery_results: Results from discover_localhost_servers()
            
        Returns:
            List of MCPServerConfig objects for discovered servers.
        """
        configs = []
        for result in discovery_results:
            transport = (
                "sse"
                if result.url.rstrip("/").endswith("/sse")
                else "streamable_http"
            )
            config = MCPServerConfig(
                name=result.name,
                command="",
                transport=transport,
                url=result.url,
                enabled=True,
            )
            configs.append(config)
        
        return configs


@dataclass(slots=True)
class MCPServerConfig:
    """Configuration for MCP server connection."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    transport: str = "stdio"  # stdio, streamable_http or legacy sse
    url: str = ""  # For HTTP transports
    timeout: float = 30.0  # Request timeout in seconds
    retry_count: int = 3  # Number of retry attempts
    retry_delay: float = 1.0  # Base retry delay in seconds


class MCPErrorMiddleware:
    """
    Middleware for handling MCP errors with retry and fallback logic.
    
    Provides:
    - Retry with exponential backoff
    - Fallback to alternative servers
    - Error logging and categorization
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._error_counts: dict[str, int] = {}
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay."""
        delay = self._base_delay * (2 ** (attempt - 1))
        return min(delay, self._max_delay)
    
    def should_retry(self, error_code: str) -> bool:
        """Determine if error is retryable."""
        retryable_codes = {
            "MCP_TIMEOUT",
            "MCP_CONNECTION_ERROR",
            "MCP_TOOL_ERROR",
        }
        return error_code in retryable_codes
    
    def get_error_count(self, tool_name: str) -> int:
        """Get error count for a tool."""
        return self._error_counts.get(tool_name, 0)
    
    def increment_error(self, tool_name: str) -> None:
        """Increment error count for a tool."""
        self._error_counts[tool_name] = self._error_counts.get(tool_name, 0) + 1
    
    def reset_error_count(self, tool_name: str) -> None:
        """Reset error count for a tool."""
        self._error_counts[tool_name] = 0


class MCPToolCache:
    """
    Cache for MCP tool schemas.
    
    Caches tool schemas to avoid repeated discovery calls.
    Supports TTL-based expiration for stale cache entries.
    """
    
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._cache: dict[str, tuple[dict[str, Any], float]] = {}
        self._ttl_seconds = ttl_seconds
    
    def get(self, tool_name: str) -> dict[str, Any] | None:
        """Get cached tool schema if not expired."""
        entry = self._cache.get(tool_name)
        if entry is None:
            return None
        
        schema, timestamp = entry
        if time.time() - timestamp > self._ttl_seconds:
            del self._cache[tool_name]
            return None
        
        return schema
    
    def set(self, tool_name: str, schema: dict[str, Any]) -> None:
        """Cache a tool schema."""
        self._cache[tool_name] = (schema, time.time())
    
    def clear(self) -> None:
        """Clear all cached schemas."""
        self._cache.clear()
    
    def get_tool_names(self) -> set[str]:
        """Get set of cached tool names."""
        return set(self._cache.keys())


class MCPConnectionPool:
    """
    Pool for reusing MCP server processes.
    
    Maintains a pool of active subprocess connections for stdio transports
    to avoid process spawn overhead on each tool call.
    """
    
    def __init__(self, max_connections: int = 5) -> None:
        self._max_connections = max_connections
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._locks: dict[str, asyncio.Lock] = {}
    
    async def get_process(
        self,
        config: MCPServerConfig,
    ) -> asyncio.subprocess.Process | None:
        """
        Get or create a process for the given server config.
        
        Returns None if process is not available or failed.
        """
        if config.transport != "stdio":
            return None
        
        name = config.name
        
        # Check if process exists and is running
        if name in self._processes:
            process = self._processes[name]
            if process.returncode is None:
                return process
        
        # Create new process
        try:
            process = await asyncio.create_subprocess_exec(
                config.command,
                *config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    **config.env,
                },
            )
            self._processes[name] = process
            self._locks[name] = asyncio.Lock()
            return process
        except Exception as exc:
            logger.warning(
                "Failed to create MCP process pool entry for %s: %s",
                name,
                exc,
            )
            return None
    
    async def call_tool_via_pool(
        self,
        config: MCPServerConfig,
        request: dict[str, Any],
        timeout: float = 30.0,
    ) -> tuple[dict[str, Any], str]:
        """
        Call a tool using pooled process.
        
        Returns (response_dict, stderr_output).
        """
        name = config.name
        
        # Get lock for this server
        lock = self._locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[name] = lock
        
        async with lock:
            process = await self.get_process(config)
            if process is None:
                raise RuntimeError(f"Cannot get process for MCP server {name}")
            
            # For pooled processes, we need to manage stdin/stdout carefully
            # Each request-response is a single call on the same process
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(
                        input=json.dumps(request).encode(),
                    ),
                    timeout=timeout,
                )
                
                response = json.loads(stdout.decode())
                return response, stderr.decode()
                
            except asyncio.TimeoutError:
                # Terminate stuck process
                process.kill()
                del self._processes[name]
                raise
            except json.JSONDecodeError:
                # Invalid response - recreate process
                process.kill()
                del self._processes[name]
                raise
    
    def close(self) -> None:
        """Close all pooled processes."""
        for name, process in list(self._processes.items()):
            if process is not None:
                try:
                    process.terminate()
                except (ProcessLookupError, AttributeError):
                    pass
        self._processes.clear()
        self._locks.clear()


class MCPGateway:
    """
    Gateway for connecting to MCP servers.
    
    Supports stdio and SSE transports for tool integration.
    Discovers tools and provides them for recovery operations.
    """
    
    def __init__(
        self,
        pool_size: int = 5,
        cache_ttl: int = 3600,
        max_retries: int = 3,
    ) -> None:
        self._servers: dict[str, MCPServerConfig] = {}
        self._tool_schemas: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._initialized = False
        self._pool = MCPConnectionPool(max_connections=pool_size)
        self._cache = MCPToolCache(ttl_seconds=cache_ttl)
        self._middleware = MCPErrorMiddleware(max_retries=max_retries)
        self._security = MCPSecurityMiddleware()
        self._sdk_clients: dict[str, Any] = {}
        self._sdk_stacks: dict[str, AsyncExitStack] = {}
        
        # Register security configs for known servers
        for server_name in ["filesystem", "sqlite", "git", "github", "slack", "gdrive", "postgres", "jira", "docker", "websearch"]:
            self._security.register_server(
                MCPServerSecurityConfig(
                    name=server_name,
                    allow_network=True,
                    allow_filesystem=True,
                ),
            )
    
    def register_server(
        self,
        config: MCPServerConfig,
    ) -> None:
        """Register an MCP server configuration."""
        self._servers[config.name] = config
        logger.info("Registered MCP server: %s", config.name)
    
    async def initialize(self) -> ToolResult:
        """Initialize all registered MCP servers and discover tools."""
        if self._initialized:
            return ToolResult.ok("MCP Gateway already initialized.")
        
        for name, config in self._servers.items():
            if config.enabled:
                try:
                    tools = await self._discover_tools(config)
                    for tool in tools:
                        tool_name = f"mcp_{name}_{tool.get('name', 'unknown')}"
                        self._tool_schemas[tool_name] = tool
                        # Also cache the schema
                        self._cache.set(tool_name, tool)
                    logger.info(
                        "Discovered %d tools from MCP server: %s",
                        len(tools),
                        name,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to initialize MCP server %s: %s",
                        name,
                        exc,
                    )
        
        self._initialized = True
        return ToolResult.ok(
            f"MCP Gateway initialized with {len(self._tool_schemas)} tools.",
            data={"tool_count": len(self._tool_schemas)},
        )

    async def _discover_tools(
        self,
        config: MCPServerConfig,
    ) -> list[dict[str, Any]]:
        """
        Discover tools from an MCP server.
        
        Supports both stdio and SSE transports.
        Sends 'tools/list' request and returns tool schemas.
        """
        client = await self._get_sdk_client(config)
        response = await asyncio.wait_for(
            client.list_tools(),
            timeout=config.timeout,
        )
        tools = getattr(response, "tools", [])

        return [
            self._normalise_sdk_tool(tool)
            for tool in tools
        ]

    @staticmethod
    def _normalise_sdk_tool(tool: Any) -> dict[str, Any]:
        """Приводит Tool из MCP SDK v1/v2 к внутренней JSON-схеме."""
        if isinstance(tool, dict):
            raw = dict(tool)
        elif hasattr(tool, "model_dump"):
            raw = tool.model_dump(
                by_alias=True,
                exclude_none=True,
            )
        else:
            raw = {
                "name": getattr(tool, "name", "unknown"),
                "description": getattr(tool, "description", ""),
            }

        parameters = (
            raw.get("inputSchema")
            or raw.get("input_schema")
            or {
                "type": "object",
                "properties": {},
            }
        )
        return {
            "name": str(raw.get("name") or "unknown"),
            "description": str(raw.get("description") or ""),
            "parameters": parameters,
            "annotations": raw.get("annotations"),
        }

    async def _get_sdk_client(
        self,
        config: MCPServerConfig,
    ) -> Any:
        """Открывает стандартную MCP SDK-сессию и переиспользует её."""
        existing = self._sdk_clients.get(config.name)
        if existing is not None:
            return existing

        stack = AsyncExitStack()
        try:
            try:
                # MCP Python SDK v2.
                from mcp import Client, StdioServerParameters
            except ImportError:
                Client = None
                from mcp import ClientSession, StdioServerParameters

            if config.transport == "stdio":
                if not config.command:
                    raise ValueError(
                        f"MCP server '{config.name}' has no command."
                    )
                from mcp.client.stdio import stdio_client

                parameters = StdioServerParameters(
                    command=config.command,
                    args=config.args,
                    # SDK intentionally inherits only a safe allow-list and
                    # adds the explicitly configured variables.
                    env=config.env or None,
                )
                transport = stdio_client(parameters)
            elif config.transport == "sse":
                if not config.url:
                    raise ValueError(
                        "SSE transport requires 'url' in config"
                    )
                from mcp.client.sse import sse_client

                transport = sse_client(config.url)
            elif config.transport == "streamable_http":
                if not config.url:
                    raise ValueError(
                        "Streamable HTTP transport requires 'url' in config"
                    )
                transport = config.url
            else:
                raise ValueError(
                    f"Unsupported MCP transport: {config.transport}"
                )

            if Client is not None:
                # v2 Client принимает URL напрямую, а stdio/SSE — как
                # transport context manager.
                client = await stack.enter_async_context(
                    Client(transport)
                )
            else:
                # Совместимость с установленной веткой SDK v1.x.
                if config.transport == "streamable_http":
                    from mcp.client.streamable_http import (
                        streamable_http_client,
                    )

                    transport = streamable_http_client(config.url)

                streams = await stack.enter_async_context(
                    transport
                )
                read_stream, write_stream = streams[:2]
                client = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await client.initialize()

            self._sdk_clients[config.name] = client
            self._sdk_stacks[config.name] = stack
            return client
        except Exception:
            await stack.aclose()
            raise

    async def _discover_tools_stdio(
        self,
        config: MCPServerConfig,
        request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Backward-compatible entrypoint backed by the official MCP SDK."""
        del request
        return await self._discover_tools(config)

    async def _discover_tools_sse(
        self,
        config: MCPServerConfig,
        request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Backward-compatible entrypoint backed by the official MCP SDK."""
        del request
        if not config.url:
            raise ValueError(f"SSE transport requires 'url' for server {config.name}")
        return await self._discover_tools(config)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """
        Call a tool from an MCP server.
        
        Args:
            tool_name: Full tool name (e.g., 'mcp_recovery_rollback')
            arguments: Tool arguments
            
        Returns:
            ToolResult with the tool execution result
        """
        if not tool_name.startswith("mcp_"):
            return ToolResult.failure(
                "INVALID_TOOL_NAME",
                f"Invalid MCP tool name format: {tool_name}",
            )

        server_name = ""
        actual_tool_name = ""
        for candidate in sorted(
            self._servers,
            key=len,
            reverse=True,
        ):
            prefix = f"mcp_{candidate}_"
            if tool_name.startswith(prefix):
                server_name = candidate
                actual_tool_name = tool_name[len(prefix):]
                break

        if not server_name or not actual_tool_name:
            return ToolResult.failure(
                "UNKNOWN_MCP_SERVER",
                f"MCP server not found for tool: {tool_name}",
            )
        
        config = self._servers.get(server_name)
        if config is None:
            return ToolResult.failure(
                "UNKNOWN_MCP_SERVER",
                f"MCP server not found: {server_name}",
            )
        
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": actual_tool_name,
                "arguments": arguments,
            },
        }
        
        # Retrying an outgoing write can duplicate a message, payment, post,
        # or other side effect when the remote service succeeded but the
        # response was lost. Reads may be retried; writes get one attempt.
        category = infer_mcp_tool_category(tool_name)
        max_attempts = (
            1
            if category == ToolCategory.NETWORK_WRITE
            else self._middleware._max_retries
        )
        last_result: ToolResult | None = None
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                if config.transport in {
                    "sse",
                    "streamable_http",
                }:
                    result = await self._call_tool_sse(config, request, actual_tool_name)
                else:
                    result = await self._call_tool_stdio(config, request, actual_tool_name)
                
                if result.success:
                    self._middleware.reset_error_count(tool_name)
                    return result

                last_result = result
                
                # Check if retryable
                if not self._middleware.should_retry(result.code):
                    return result
                
                self._middleware.increment_error(tool_name)
                
                if attempt < max_attempts - 1:
                    delay = self._middleware.calculate_delay(attempt + 1)
                    logger.warning(
                        "Retrying MCP tool %s (attempt %d/%d) after %s seconds",
                        tool_name,
                        attempt + 1,
                        max_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    
            except asyncio.TimeoutError as exc:
                last_error = exc
                self._middleware.increment_error(tool_name)
                if attempt < max_attempts - 1:
                    delay = self._middleware.calculate_delay(attempt + 1)
                    await asyncio.sleep(delay)
                continue
            except Exception as exc:
                last_error = exc
                self._middleware.increment_error(tool_name)
                if attempt < max_attempts - 1:
                    delay = self._middleware.calculate_delay(attempt + 1)
                    await asyncio.sleep(delay)
                continue
        
        if last_result is not None:
            return last_result
        if isinstance(last_error, asyncio.TimeoutError):
            return ToolResult.failure(
                "MCP_TIMEOUT",
                f"MCP tool '{actual_tool_name}' timed out after {config.timeout:g} seconds.",
                retryable=True,
            )
        if last_error is not None:
            return ToolResult.failure(
                "MCP_TOOL_ERROR",
                f"MCP tool '{actual_tool_name}' failed: {_redact_mcp_error(last_error, config)}",
                retryable=True,
            )
        return ToolResult.failure(
            "MCP_TOOL_ERROR",
            f"MCP tool '{actual_tool_name}' failed without an error response.",
        )

    async def _call_tool_stdio(
        self,
        config: MCPServerConfig,
        request: dict[str, Any],
        tool_name: str,
    ) -> ToolResult:
        """Call an stdio tool through the persistent official SDK session."""
        arguments = (
            request.get("params", {})
            .get("arguments", {})
        )
        return await self._call_tool_with_sdk(
            config,
            tool_name,
            arguments,
        )

    async def _call_tool_sse(
        self,
        config: MCPServerConfig,
        request: dict[str, Any],
        tool_name: str,
    ) -> ToolResult:
        """Call an HTTP/SSE tool through the persistent SDK session."""
        if not config.url:
            return ToolResult.failure(
                "MCP_CONFIG_ERROR",
                "HTTP transport requires 'url' in config",
            )
        arguments = (
            request.get("params", {})
            .get("arguments", {})
        )
        return await self._call_tool_with_sdk(
            config,
            tool_name,
            arguments,
        )

    async def _call_tool_with_sdk(
        self,
        config: MCPServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        client = await self._get_sdk_client(config)
        response = await asyncio.wait_for(
            client.call_tool(tool_name, arguments),
            timeout=config.timeout,
        )

        is_error = bool(
            getattr(
                response,
                "is_error",
                getattr(response, "isError", False),
            )
        )
        structured_content = getattr(
            response,
            "structured_content",
            getattr(response, "structuredContent", None),
        )
        content_blocks: list[dict[str, Any]] = []
        text_parts: list[str] = []

        for block in getattr(response, "content", []) or []:
            if isinstance(block, dict):
                raw_block = dict(block)
            elif hasattr(block, "model_dump"):
                raw_block = block.model_dump(
                    by_alias=True,
                    exclude_none=True,
                )
            else:
                raw_block = {
                    "type": getattr(block, "type", "unknown"),
                    "text": getattr(block, "text", ""),
                }

            content_blocks.append(raw_block)
            block_text = raw_block.get("text")
            if isinstance(block_text, str) and block_text:
                text_parts.append(block_text)

        message = "\n".join(text_parts).strip()
        if not message and structured_content is not None:
            message = json.dumps(
                structured_content,
                ensure_ascii=False,
            )
        if not message:
            message = (
                f"MCP tool '{tool_name}' returned no text."
            )
        message = _redact_mcp_error(message, config)

        data = {
            "structured_content": structured_content,
            "content": content_blocks,
            "server": config.name,
            "tool": tool_name,
        }
        if is_error:
            return ToolResult.failure(
                "MCP_TOOL_ERROR",
                message,
                data=data,
            )
        return ToolResult.ok(message, data=data)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get all discovered tool schemas for model consumption."""
        schemas = []
        for name, schema in self._tool_schemas.items():
            schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": schema.get("description", ""),
                    "parameters": schema.get("parameters", {
                        "type": "object",
                        "properties": {},
                    }),
                },
            })
        return schemas

    def get_cached_tool_schema(self, tool_name: str) -> dict[str, Any] | None:
        """Get cached tool schema if available."""
        return self._cache.get(tool_name)

    def get_available_tools(self) -> set[str]:
        """Get set of available MCP tool names."""
        return set(self._tool_schemas.keys())

    async def close(self) -> None:
        """Закрывает MCP-сессии и запущенные ими subprocesses."""
        stacks = list(self._sdk_stacks.items())
        self._sdk_clients.clear()
        self._sdk_stacks.clear()

        for server_name, stack in reversed(stacks):
            try:
                await stack.aclose()
            except Exception:
                logger.exception(
                    "Failed to close MCP server: %s",
                    server_name,
                )

        self._pool.close()
        self._initialized = False

    async def register_with_registry(
        self,
        registry: Any,
    ) -> int:
        """
        Register MCP tools with ToolRegistry.
        
        Returns number of tools registered.
        """
        count = 0
        for tool_name, schema in self._tool_schemas.items():
            try:
                server_name = next(
                    (
                        server
                        for server in sorted(
                            self._servers,
                            key=len,
                            reverse=True,
                        )
                        if tool_name.startswith(
                            f"mcp_{server}_"
                        )
                    ),
                    "",
                )
                actual_tool_name = (
                    tool_name[len(f"mcp_{server_name}_"):]
                    if server_name
                    else tool_name
                )
                # Infer risk and category for the tool
                risk = infer_mcp_tool_risk(
                    actual_tool_name,
                    schema.get("description", ""),
                )
                category = infer_mcp_tool_category(
                    actual_tool_name,
                    schema.get("description", ""),
                )
                
                # Register security info for the tool
                self._security.register_tool(
                    MCPToolSecurityInfo(
                        tool_name=tool_name,
                        server_name=server_name,
                        risk=risk,
                        category=category,
                        requires_confirmation=risk in {RiskLevel.EXECUTE, RiskLevel.DESTRUCTIVE},
                        audit_redact=["password", "token", "api_key", "secret"],
                    ),
                )
                
                # MCP transports принадлежат текущему event loop. Синхронная
                # обёртка с asyncio.run() создавала новый loop в worker thread
                # ToolRunner и ломала живые stdio/SSE-сессии.
                def make_handler(name: str) -> Callable[..., Any]:
                    async def handler(**kwargs) -> ToolResult:
                        return await self.call_tool(name, kwargs)

                    return handler
                
                self._handlers[tool_name] = make_handler(tool_name)
                
                # Register with registry
                registry.register(
                    schema={
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": schema.get("description", ""),
                            "parameters": schema.get("parameters", {
                                "type": "object",
                                "properties": {},
                            }),
                        },
                    },
                    handler=self._handlers[tool_name],
                    risk=risk,
                    category=category,
                )
                count += 1
            except ValueError:
                # Tool already registered
                pass
        
        return count


# Pre-defined MCP server configurations for recovery
DEFAULT_RECOVERY_SERVERS: list[MCPServerConfig] = [
    MCPServerConfig(
        name="recovery",
        command="python",
        args=["-m", "mcp_server_recovery"],
        env={"MCP_RECOVERY_MODE": "auto_rollback"},
        enabled=True,
    ),
]
