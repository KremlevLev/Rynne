from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import asyncio
import sys

from integrations.telegram_mcp.server import _bounded_limit, _message_payload, mcp
from modules.agent.mcp_integration import create_bundled_telegram_server_config
from modules.agent.mcp_gateway import MCPGateway, MCPServerConfig
from modules.agent.mcp_security import infer_mcp_tool_category, infer_mcp_tool_risk
from modules.tools.base import RiskLevel, ToolCategory
from modules.tools.policy import PolicyContext, PolicyDecision, evaluate_policy
from modules.tools.selection import select_tools_for_request
from scripts.setup_telegram_mcp import _upsert_env


def test_bundled_telegram_mcp_is_opt_in(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NOVA_TELEGRAM_MCP_ENABLED", raising=False)
    assert create_bundled_telegram_server_config(project_root=tmp_path) is None


def test_bundled_telegram_mcp_uses_separate_stdio_process(monkeypatch, tmp_path: Path) -> None:
    server = tmp_path / "integrations" / "telegram_mcp" / "server.py"
    server.parent.mkdir(parents=True)
    server.write_text("", encoding="utf-8")
    monkeypatch.setenv("NOVA_TELEGRAM_MCP_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "secret-hash")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", r"C:\Nova\telegram")

    config = create_bundled_telegram_server_config(
        project_root=tmp_path,
        python_executable=r"C:\Python\python.exe",
    )

    assert config is not None
    assert config.name == "telegram"
    assert config.command == r"C:\Python\python.exe"
    assert config.args == [str(server)]
    assert config.env["TELEGRAM_SESSION_PATH"] == r"C:\Nova\telegram"


def test_setup_updates_env_without_duplicate_secrets(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEYS=x\nTELEGRAM_API_HASH=old\n", encoding="utf-8")
    _upsert_env(
        env_file,
        {
            "NOVA_TELEGRAM_MCP_ENABLED": "true",
            "TELEGRAM_API_HASH": "new",
        },
    )
    text = env_file.read_text(encoding="utf-8")
    assert "GROQ_API_KEYS=x" in text
    assert text.count("TELEGRAM_API_HASH=") == 1
    assert "TELEGRAM_API_HASH=new" in text


def test_telegram_send_is_confirmed_network_write() -> None:
    name = "mcp_telegram_send_message"
    description = "Send a message to a Telegram chat."
    risk = infer_mcp_tool_risk(name, description)
    category = infer_mcp_tool_category(name, description)

    assert risk == RiskLevel.EXECUTE
    assert category == ToolCategory.NETWORK_WRITE
    decision = evaluate_policy(
        PolicyContext(
            tool_name=name,
            tool_category=category,
            risk=risk,
            arguments={"chat": "Alex", "text": "Hi"},
            operation_id="op",
            session_id="session",
            turn_id="turn",
        )
    )
    assert decision == PolicyDecision.REQUIRE_CONFIRMATION


def test_telegram_tools_are_selected_for_message_request() -> None:
    available = {
        "mcp_telegram_list_chats",
        "mcp_telegram_read_messages",
        "mcp_telegram_send_message",
        "browser_open_url",
    }
    selected = select_tools_for_request(
        "прочитай последние сообщения в телеграме",
        available,
        max_tools=10,
    )
    assert "mcp_telegram_read_messages" in selected
    assert "mcp_telegram_list_chats" in selected


def test_telegram_payload_is_bounded_and_serializable() -> None:
    message = SimpleNamespace(
        id=7,
        date=datetime(2026, 8, 9, tzinfo=timezone.utc),
        sender_id=42,
        out=False,
        message="x" * 9000,
    )
    payload = _message_payload(message)
    assert payload["id"] == 7
    assert len(payload["text"]) == 8000
    assert _bounded_limit(0) == 1
    assert _bounded_limit(999) == 100


def test_telegram_mcp_exposes_small_auditable_tool_surface() -> None:
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    assert set(tools) == {
        "get_status",
        "list_chats",
        "read_messages",
        "search_messages",
        "send_message",
    }
    assert tools["read_messages"].annotations.readOnlyHint is True
    assert tools["send_message"].annotations.readOnlyHint is False


def test_telegram_mcp_stdio_discovery_works_without_logging_in() -> None:
    async def scenario() -> None:
        gateway = MCPGateway(max_retries=1)
        gateway.register_server(
            MCPServerConfig(
                name="telegram",
                command=sys.executable,
                args=[str(
                    Path(__file__).resolve().parents[1]
                    / "integrations" / "telegram_mcp" / "server.py"
                )],
                env={
                    "TELEGRAM_API_ID": "12345",
                    "TELEGRAM_API_HASH": "not-a-real-secret",
                },
                timeout=15,
            )
        )
        try:
            result = await gateway.initialize()
            assert result.success
            assert gateway.get_available_tools() == {
                "mcp_telegram_get_status",
                "mcp_telegram_list_chats",
                "mcp_telegram_read_messages",
                "mcp_telegram_search_messages",
                "mcp_telegram_send_message",
            }
        finally:
            await gateway.close()

    asyncio.run(scenario())
