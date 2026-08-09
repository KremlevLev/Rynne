"""Small, auditable Telegram MTProto MCP server for Nova.

The process is intentionally separate from Nova Core. It never performs an
interactive login: run ``scripts/setup_telegram_mcp.py`` once and then restart
Core. Secrets and the Telethon session are not exposed through MCP schemas.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


SERVER_NAME = "Nova Telegram"
mcp = FastMCP(
    SERVER_NAME,
    instructions=(
        "Use these tools for the user's real Telegram account. Prefer read-only "
        "tools for finding chats and messages. Never claim a message was sent "
        "unless send_message returned success."
    ),
    log_level="WARNING",
)

_client: Any | None = None
_client_lock = asyncio.Lock()


def _settings() -> tuple[int, str, Path]:
    raw_api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    raw_session = os.getenv("TELEGRAM_SESSION_PATH", "").strip()
    if not raw_api_id.isdigit() or not api_hash:
        raise RuntimeError(
            "Telegram MCP is not configured. Run: py scripts/setup_telegram_mcp.py"
        )
    session_path = Path(raw_session).expanduser() if raw_session else (
        Path(os.getenv("LOCALAPPDATA", Path.home()))
        / "Nova" / "telegram-mcp" / "nova"
    )
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return int(raw_api_id), api_hash, session_path


async def _get_client() -> Any:
    global _client
    async with _client_lock:
        if _client is None:
            try:
                from telethon import TelegramClient
            except ImportError as exc:
                raise RuntimeError(
                    "Telethon is not installed. Run: py -m pip install -r requirements.txt"
                ) from exc
            api_id, api_hash, session_path = _settings()
            _client = TelegramClient(str(session_path), api_id, api_hash)
        if not _client.is_connected():
            await _client.connect()
        if not await _client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized. Run: py scripts/setup_telegram_mcp.py"
            )
        return _client


def _bounded_limit(limit: int, *, maximum: int = 100) -> int:
    return max(1, min(maximum, int(limit)))


def _dialog_title(dialog: Any) -> str:
    return str(getattr(dialog, "name", None) or getattr(dialog, "title", None) or "")


async def _resolve_dialog(client: Any, query: str) -> Any:
    needle = " ".join(str(query).casefold().split()).lstrip("@")
    if not needle:
        raise ValueError("Chat name is empty.")
    dialogs = await client.get_dialogs(limit=250)
    ranked: list[tuple[int, Any]] = []
    for dialog in dialogs:
        title = _dialog_title(dialog).casefold()
        username = str(getattr(dialog.entity, "username", "") or "").casefold()
        if needle == title or needle == username:
            ranked.append((0, dialog))
        elif needle in title or needle in username:
            ranked.append((1, dialog))
    if not ranked:
        raise LookupError(f"Telegram chat '{query}' was not found.")
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def _message_payload(message: Any) -> dict[str, Any]:
    date = getattr(message, "date", None)
    return {
        "id": int(getattr(message, "id", 0) or 0),
        "date": date.isoformat() if isinstance(date, datetime) else str(date or ""),
        "sender_id": getattr(message, "sender_id", None),
        "outgoing": bool(getattr(message, "out", False)),
        "text": str(getattr(message, "message", "") or "")[:8000],
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def get_status() -> dict[str, Any]:
    """Check whether the personal Telegram MTProto session is connected."""
    client = await _get_client()
    me = await client.get_me()
    return {
        "connected": client.is_connected(),
        "authorized": True,
        "user_id": getattr(me, "id", None),
        "username": getattr(me, "username", None),
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def list_chats(query: str = "", limit: int = 30) -> dict[str, Any]:
    """List recent Telegram chats, optionally filtering by title or username."""
    client = await _get_client()
    needle = " ".join(str(query).casefold().split()).lstrip("@")
    dialogs = await client.get_dialogs(limit=max(100, _bounded_limit(limit)))
    items = []
    for dialog in dialogs:
        title = _dialog_title(dialog)
        username = str(getattr(dialog.entity, "username", "") or "")
        if needle and needle not in title.casefold() and needle not in username.casefold():
            continue
        items.append({
            "id": getattr(dialog.entity, "id", None),
            "title": title,
            "username": username or None,
            "unread_count": int(getattr(dialog, "unread_count", 0) or 0),
        })
        if len(items) >= _bounded_limit(limit):
            break
    return {"count": len(items), "chats": items}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def read_messages(chat: str, limit: int = 20) -> dict[str, Any]:
    """Read recent messages from a Telegram chat selected by name or username."""
    client = await _get_client()
    dialog = await _resolve_dialog(client, chat)
    messages = await client.get_messages(dialog.entity, limit=_bounded_limit(limit))
    return {
        "chat": _dialog_title(dialog),
        "messages": [_message_payload(message) for message in reversed(messages)],
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def search_messages(query: str, chat: str = "", limit: int = 20) -> dict[str, Any]:
    """Search Telegram message history globally or inside one named chat."""
    client = await _get_client()
    clean_query = " ".join(str(query).strip().split())
    if not clean_query:
        raise ValueError("Search query is empty.")
    entity = None
    resolved_chat = None
    if str(chat).strip():
        dialog = await _resolve_dialog(client, chat)
        entity = dialog.entity
        resolved_chat = _dialog_title(dialog)
    messages = await client.get_messages(
        entity,
        limit=_bounded_limit(limit),
        search=clean_query,
    )
    return {
        "query": clean_query,
        "chat": resolved_chat,
        "messages": [_message_payload(message) for message in messages],
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def send_message(chat: str, text: str) -> dict[str, Any]:
    """Send a Telegram message; the runtime permission mode controls approval."""
    clean_text = str(text).strip()
    if not clean_text:
        raise ValueError("Message text is empty.")
    if len(clean_text) > 4096:
        raise ValueError("Telegram message exceeds 4096 characters.")
    client = await _get_client()
    dialog = await _resolve_dialog(client, chat)
    sent = await client.send_message(dialog.entity, clean_text)
    return {
        "sent": True,
        "chat": _dialog_title(dialog),
        "message_id": getattr(sent, "id", None),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
