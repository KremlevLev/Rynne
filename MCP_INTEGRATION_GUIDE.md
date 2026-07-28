# MCP Integration Guide for Nova

Nova uses the official MCP Python SDK for the protocol lifecycle, transport,
tool discovery and tool calls. Do not add ad-hoc JSON-RPC subprocess code and
do not assume that an npm package exists merely because its name looks right.

## Configure trusted servers

Point `NOVA_MCP_CONFIG` to a JSON file:

```env
NOVA_MCP_CONFIG=C:\Users\you\.config\nova\mcp.json
NOVA_MCP_AUTO_DISCOVERY=false
```

The file accepts the common `mcpServers` format:

```json
{
  "mcpServers": {
    "local_project": {
      "command": "python",
      "args": ["C:\\tools\\project_server.py"],
      "env": {
        "PROJECT_TOKEN": "${PROJECT_TOKEN}"
      }
    },
    "internal_api": {
      "transport": "streamable_http",
      "url": "http://127.0.0.1:8000/mcp",
      "timeout": 30
    },
    "legacy_service": {
      "transport": "sse",
      "url": "http://127.0.0.1:8001/sse"
    }
  }
}
```

Supported transports:

- `stdio` — default when `command` is present;
- `streamable_http` — default when only `url` is present;
- `sse` — compatibility with legacy servers.

Use `${ENV_NAME}` for secrets. Nova resolves the value locally when starting
the server; the value does not become part of a tool schema or model prompt.

## Runtime flow

1. `bootstrap_mcp_with_auto_discovery()` reads the explicit config.
2. `MCPGateway` opens an official SDK client session and performs the MCP
   handshake.
3. Tools are discovered once and registered as
   `mcp_<server_name>_<tool_name>`.
4. Risk and category metadata are inferred before registration.
5. Capability routing exposes only relevant MCP tools to the model.
6. Tool calls reuse the same live SDK session.
7. `MCPGateway.close()` shuts down sessions and stdio subprocesses.

Auto-discovery is optional and disabled by default. When enabled, Nova probes
configured localhost ports using a real SDK handshake, not a raw `tools/list`
POST. Prefer an explicit config for predictable startup and a clear trust
boundary.

## Adding an integration

Before adding a server:

1. Verify it in the official MCP Registry or its audited source repository.
2. Review filesystem/network access and all destructive tools.
3. Pin the server version outside Nova where possible.
4. Put credentials in environment variables, never in committed JSON.
5. Start with read-only tools and test discovery plus one real tool call.

Protocol and SDK references:

- https://modelcontextprotocol.io/
- https://github.com/modelcontextprotocol/python-sdk
