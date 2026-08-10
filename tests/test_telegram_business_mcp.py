from __future__ import annotations

from pathlib import Path
import asyncio
import sys

import pytest
import integrations.telegram_bot_mcp.server as business_server

from integrations.telegram_bot_mcp.server import (
    _connect,
    _control_start_text,
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


def test_spoken_short_name_resolves_full_contact(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_STORE_PATH", str(tmp_path / "names.sqlite3"))
    connection = _connect()
    try:
        _store_update(connection, {
            "business_message": {
                "business_connection_id": "connection-1",
                "message_id": 10,
                "date": 1_786_200_002,
                "from": {"id": 44},
                "chat": {
                    "id": 44,
                    "first_name": "Владислав",
                    "last_name": "Бородинский",
                    "username": "vladislav_b",
                },
                "text": "привет",
            }
        })
        connection.commit()

        chat = _resolve_chat(connection, "Влад")
        assert chat["title"] == "Владислав Бородинский"
    finally:
        connection.close()


def test_cyrillic_name_resolves_transliterated_username(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_STORE_PATH", str(tmp_path / "translit.sqlite3"))
    connection = _connect()
    try:
        _store_update(connection, {
            "business_message": {
                "business_connection_id": "connection-1",
                "message_id": 11,
                "date": 1_786_200_003,
                "from": {"id": 47},
                "chat": {
                    "id": 47,
                    "first_name": "son😭✌️🥀",
                    "username": "Vladosik585",
                },
                "text": "привет",
            }
        })
        connection.commit()

        assert _resolve_chat(connection, "Влад")["username"] == "Vladosik585"
        assert _resolve_chat(connection, "Владу")["username"] == "Vladosik585"
        assert _resolve_chat(connection, "Влада")["username"] == "Vladosik585"
    finally:
        connection.close()


def test_resolver_defers_approval_to_runtime_permission_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_STORE_PATH", str(tmp_path / "permission-mode.sqlite3"))
    connection = _connect()
    try:
        _store_update(connection, {
            "business_message": {
                "business_connection_id": "connection-1",
                "message_id": 12,
                "date": 1_786_200_004,
                "from": {"id": 48},
                "chat": {"id": 48, "first_name": "Vlad", "username": "vladosik585"},
                "text": "hello",
            }
        })
        connection.commit()
    finally:
        connection.close()

    async def no_updates() -> int:
        return 0

    monkeypatch.setattr(business_server, "_sync_updates", no_updates)
    result = asyncio.run(business_server.resolve_chat("@vladosik585"))

    assert result["status"] == "resolved"
    assert "runtime permission mode" in result["instruction"]
    assert "still requires user confirmation" not in result["instruction"]


def test_ambiguous_short_name_requires_clarification(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_STORE_PATH", str(tmp_path / "ambiguous.sqlite3"))
    connection = _connect()
    try:
        for chat_id, last_name in ((45, "Бородинский"), (46, "Петров")):
            _store_update(connection, {
                "business_message": {
                    "business_connection_id": "connection-1",
                    "message_id": chat_id,
                    "date": 1_786_200_000 + chat_id,
                    "from": {"id": chat_id},
                    "chat": {
                        "id": chat_id,
                        "first_name": "Владислав",
                        "last_name": last_name,
                        "username": f"vlad{chat_id}",
                    },
                    "text": "test",
                }
            })
        connection.commit()

        with pytest.raises(LookupError, match="ambiguous"):
            _resolve_chat(connection, "Влад")
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


def test_read_messages_without_chat_returns_global_recent_messages(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_STORE_PATH", str(tmp_path / "global.sqlite3"))
    connection = _connect()
    try:
        _store_update(connection, {
            "business_message": {
                "business_connection_id": "connection-1",
                "message_id": 9,
                "date": 1_786_200_001,
                "from": {"id": 43},
                "chat": {"id": 43, "first_name": "XIII", "username": "xiii"},
                "text": "приветствую",
            }
        })
        connection.commit()
    finally:
        connection.close()

    async def no_updates() -> int:
        return 0

    monkeypatch.setattr(business_server, "_sync_updates", no_updates)
    result = asyncio.run(business_server.read_messages())
    assert result["scope"] == "all_observed_chats"
    assert result["messages"][0]["chat"] == "XIII"
    assert result["messages"][0]["text"] == "приветствую"


def test_business_mcp_surface_and_send_security() -> None:
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    assert set(tools) == {
        "get_status", "list_chats", "poll_control_approvals",
        "poll_control_commands", "read_messages", "resolve_chat",
        "send_control_approval", "send_control_reply", "send_message",
    }
    assert tools["read_messages"].annotations.readOnlyHint is True
    assert tools["resolve_chat"].annotations.readOnlyHint is True
    assert tools["send_message"].annotations.readOnlyHint is False
    assert tools["poll_control_commands"].annotations.readOnlyHint is True
    assert tools["poll_control_approvals"].annotations.readOnlyHint is True
    assert tools["send_control_approval"].annotations.readOnlyHint is False
    assert tools["send_control_reply"].annotations.readOnlyHint is False

    name = "mcp_telegram_business_send_message"
    assert infer_mcp_tool_risk(name, "Send a Telegram message") == RiskLevel.EXECUTE
    assert infer_mcp_tool_category(name, "Send a Telegram message") == ToolCategory.NETWORK_WRITE


def test_start_text_explains_pairing_and_authorized_usage() -> None:
    pairing = _control_start_text(123456789, authorized=False)
    assert "123456789" in pairing
    assert "Настройки" in pairing
    authorized = _control_start_text(123456789, authorized=True)
    assert "Nova Remote подключена" in authorized
    assert "обычными фразами" in authorized
    assert "/status" in authorized
    assert "/stop" in authorized


def test_authorized_callback_becomes_remote_approval(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_STORE_PATH", str(tmp_path / "approvals.sqlite3"))
    monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", "42")
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        business_server,
        "_api",
        lambda method, payload=None: calls.append((method, payload or {})) or True,
    )
    connection = _connect()
    try:
        _store_update(connection, {
            "update_id": 501,
            "callback_query": {
                "id": "callback-1",
                "from": {"id": 42},
                "data": "nova:approve:operation_abc",
                "message": {
                    "message_id": 11,
                    "chat": {"id": 42, "type": "private"},
                },
            },
        })
        connection.commit()
        row = connection.execute("SELECT * FROM control_approvals").fetchone()
        assert row["operation_id"] == "operation_abc"
        assert row["decision"] == "approve"
        assert [call[0] for call in calls] == ["answerCallbackQuery", "editMessageReplyMarkup"]
    finally:
        connection.close()


def test_authorized_bot_message_becomes_remote_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_STORE_PATH", str(tmp_path / "remote.sqlite3"))
    monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", "42")
    connection = _connect()
    try:
        _store_update(connection, {
            "update_id": 101,
            "message": {
                "message_id": 7,
                "date": 1_786_200_000,
                "from": {"id": 42, "username": "lev"},
                "chat": {"id": 42, "type": "private"},
                "text": "проверь статус проекта",
            },
        })
        _store_update(connection, {
            "update_id": 102,
            "message": {
                "message_id": 8,
                "date": 1_786_200_001,
                "from": {"id": 99, "username": "stranger"},
                "chat": {"id": 99, "type": "private"},
                "text": "удали все файлы",
            },
        })
        connection.commit()
        rows = connection.execute("SELECT * FROM control_commands").fetchall()
        assert len(rows) == 1
        assert rows[0]["user_id"] == 42
        assert rows[0]["text"] == "проверь статус проекта"
    finally:
        connection.close()


def test_telegram_api_error_keeps_description_without_leaking_token(monkeypatch) -> None:
    class FakeResponse:
        ok = False
        status_code = 400
        url = "https://api.telegram.org/bot123456:super-secret-token/sendMessage"

        @staticmethod
        def json() -> dict:
            return {
                "ok": False,
                "description": "Bad Request: chat not found",
            }

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:super-secret-token")
    monkeypatch.setattr(business_server.requests, "post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(RuntimeError) as exc_info:
        business_server._api("sendMessage", {"chat_id": 1, "text": "hello"})

    message = str(exc_info.value)
    assert message == "Telegram API sendMessage failed (400): Bad Request: chat not found"
    assert "super-secret-token" not in message


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
                "mcp_telegram_business_poll_control_approvals",
                "mcp_telegram_business_poll_control_commands",
                "mcp_telegram_business_read_messages",
                "mcp_telegram_business_resolve_chat",
                "mcp_telegram_business_send_control_approval",
                "mcp_telegram_business_send_control_reply",
                "mcp_telegram_business_send_message",
            }
        finally:
            await gateway.close()

    asyncio.run(scenario())
