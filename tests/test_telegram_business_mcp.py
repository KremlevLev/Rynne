from __future__ import annotations

from pathlib import Path
import asyncio
import sys

import pytest

from integrations.telegram_bot_mcp.server import (
    _connect,
    _resolve_chat,
    _store_update,
    mcp,
)
from modules.agent.mcp_integration import create_bundled_telegram_bot_server_config
from modules.agent.mcp_gateway import MCPGateway, MCPServerConfig
from modules.agent.mcp_security import infer_mcp_tool_category, infer_mcp_tool_risk
from modules.tools.base import RiskLevel, ToolCategory


def test_business_bot_config_is_enabled_by_token(monkeypatch, tmp_path: Path) -> None:
    server = tmp_path / "integrations" / "telegram_bot_mcp" / "server.py"
    server.parent.mkdir(parents=True)
    server.write_text("", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:secret-token")

    config = create_bundled_telegram_bot_server_config(
        project_root=tmp_path,
        python_executable=r"C:\Python\python.exe",
    )

    assert config is not None
    assert config.name == "telegram_business"
    assert config.args == [str(server)]
    assert config.env == {"TELEGRAM_BOT_TOKEN": "123456:secret-token"}


def test_business_bot_config_is_disabled_without_token(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert create_bundled_telegram_bot_server_config() is None


def test_business_update_is_cached_and_resolved(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "telegram.sqlite3"
    monkeypatch.setenv("TELEGRAM_BOT_STORE_PATH", str(store))
    connection = _connect()
    try:
        _store_update(connection, {
            "business_connection": {
                "id": "connection-1",
                "user": {"id": 1, "username": "lev"},
                "is_enabled": True,
                "rights": {"can_reply": True},
            }
        })
        _store_update(connection, {
            "business_message": {
                "business_connection_id": "connection-1",
                "message_id": 7,
                "date": 1_786_200_000,
                "from": {"id": 42},
                "chat": {"id": 42, "first_name": "Alex", "username": "alex42"},
                "text": "hello Nova",
            }
        })
        connection.commit()

        chat = _resolve_chat(connection, "alex")
        assert chat["chat_id"] == 42
        message = connection.execute("SELECT * FROM messages").fetchone()
        assert message["text"] == "hello Nova"
    finally:
        connection.close()


def test_unknown_business_chat_has_actionable_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_STORE_PATH", str(tmp_path / "empty.sqlite3"))
    connection = _connect()
    try:
        with pytest.raises(LookupError, match="has not been observed"):
            _resolve_chat(connection, "Nobody")
    finally:
        connection.close()


def test_business_mcp_surface_and_send_security() -> None:
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    assert set(tools) == {"get_status", "list_chats", "read_messages", "send_message"}
    assert tools["read_messages"].annotations.readOnlyHint is True
    assert tools["send_message"].annotations.readOnlyHint is False

    name = "mcp_telegram_business_send_message"
    assert infer_mcp_tool_risk(name, "Send a Telegram message") == RiskLevel.EXECUTE
    assert infer_mcp_tool_category(name, "Send a Telegram message") == ToolCategory.NETWORK_WRITE


def test_business_mcp_stdio_discovery_does_not_contact_telegram() -> None:
    async def scenario() -> None:
        gateway = MCPGateway(max_retries=1)
        gateway.register_server(MCPServerConfig(
            name="telegram_business",
            command=sys.executable,
            args=[str(
                Path(__file__).resolve().parents[1]
                / "integrations" / "telegram_bot_mcp" / "server.py"
            )],
            env={"TELEGRAM_BOT_TOKEN": "123456:not-a-real-token"},
            timeout=15,
        ))
        try:
            result = await gateway.initialize()
            assert result.success
            assert gateway.get_available_tools() == {
                "mcp_telegram_business_get_status",
                "mcp_telegram_business_list_chats",
                "mcp_telegram_business_read_messages",
                "mcp_telegram_business_send_message",
            }
        finally:
            await gateway.close()

    asyncio.run(scenario())
