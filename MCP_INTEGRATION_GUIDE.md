# MCP Integration Guide for Rynne

Rynne uses the official MCP Python SDK for the protocol lifecycle, transport,
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

Use `${ENV_NAME}` for secrets. Rynne resolves the value locally when starting
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

Auto-discovery is optional and disabled by default. When enabled, Rynne probes
configured localhost ports using a real SDK handshake, not a raw `tools/list`
POST. Prefer an explicit config for predictable startup and a clear trust
boundary.

## Adding an integration

Before adding a server:

1. Verify it in the official MCP Registry or its audited source repository.
2. Review filesystem/network access and all destructive tools.
3. Pin the server version outside Rynne where possible.
4. Put credentials in environment variables, never in committed JSON.
5. Start with read-only tools and test discovery plus one real tool call.

## Bundled Telegram Business Bot MCP (recommended)

Add `TELEGRAM_BOT_TOKEN` in the desktop Settings → Integrations screen. The
official Bot API connection requires no `api_id` or `api_hash`. After the bot is
connected to the user's Telegram Business account, Rynne exposes status,
observed chats, cached messages, and confirmed sending as MCP tools. Only events
received after connection are available; Telegram does not provide arbitrary
historical chats to bots.

## Bundled personal Telegram MCP (advanced)

Rynne includes an opt-in, local MTProto MCP server with a deliberately small
surface: connection status, chat listing, recent messages, message search and
sending. It runs as a separate stdio process and uses the user's real Telegram
account through Telethon; it is not a Telegram bot.

1. Create an application at `https://my.telegram.org/apps` and keep its API
   hash private.
2. Install dependencies and authorize once in an interactive terminal:

```powershell
py -m pip install -r requirements.txt
py scripts/setup_telegram_mcp.py
```

3. Restart Rynne Core. The server is registered automatically when
   `NOVA_TELEGRAM_MCP_ENABLED=true` is present in the local `.env`.

The Telethon session is stored under `%LOCALAPPDATA%\Rynne\telegram-mcp` by
default. Never commit `.env` or the `.session` file. Reading tools run without
prompts; `send_message` is classified as a network write and always requires
visible confirmation in Rynne before the MCP call is allowed.

Protocol and SDK references:

- https://modelcontextprotocol.io/
- https://github.com/modelcontextprotocol/python-sdk
