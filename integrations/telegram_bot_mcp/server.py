"""Local Telegram Business Bot MCP server.

The server uses the official HTTP Bot API. It stores only business updates
received after the bot was connected; Telegram's Bot API does not expose the
account's arbitrary historical chat list.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


mcp = FastMCP(
    "Nova Telegram Business",
    instructions=(
        "Use these tools for Telegram chats delegated to the user's connected "
        "Business bot. Never claim that a message was sent unless send_message "
        "returns sent=true. Only chats observed after connection are available."
    ),
    log_level="WARNING",
)


def _token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or ":" not in token:
        raise RuntimeError("Telegram Bot token is not configured in Nova settings.")
    return token


def _db_path() -> Path:
    configured = os.getenv("TELEGRAM_BOT_STORE_PATH", "").strip()
    path = Path(configured).expanduser() if configured else (
        Path(os.getenv("LOCALAPPDATA", Path.home()))
        / "Nova" / "telegram-business" / "messages.sqlite3"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS connections (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            rights_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            connection_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            last_message_at INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS messages (
            connection_id TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            date INTEGER NOT NULL DEFAULT 0,
            sender_id INTEGER,
            outgoing INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (connection_id, chat_id, message_id)
        );
        """
    )
    return connection


@contextmanager
def _database():
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _api(method: str, payload: dict[str, Any] | None = None) -> Any:
    response = requests.post(
        f"https://api.telegram.org/bot{_token()}/{method}",
        json=payload or {},
        timeout=20,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(str(body.get("description") or "Telegram API error"))
    return body.get("result")


def _chat_title(chat: dict[str, Any]) -> str:
    return str(
        chat.get("title")
        or " ".join(part for part in [chat.get("first_name"), chat.get("last_name")] if part)
        or chat.get("username")
        or chat.get("id")
    )


def _store_update(connection: sqlite3.Connection, update: dict[str, Any]) -> None:
    business = update.get("business_connection")
    if isinstance(business, dict) and business.get("id"):
        user = business.get("user") or {}
        connection.execute(
            """INSERT INTO connections(id, user_id, username, enabled, rights_json)
               VALUES(?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET user_id=excluded.user_id,
               username=excluded.username, enabled=excluded.enabled,
               rights_json=excluded.rights_json""",
            (
                str(business["id"]), user.get("id"), str(user.get("username") or ""),
                int(bool(business.get("is_enabled", True))),
                json.dumps(business.get("rights") or {}, ensure_ascii=False),
            ),
        )

    message = update.get("business_message") or update.get("edited_business_message")
    if not isinstance(message, dict):
        return
    connection_id = str(message.get("business_connection_id") or "")
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if not connection_id or chat_id is None or message_id is None:
        return
    sender = message.get("from") or {}
    connection.execute(
        """INSERT INTO chats(chat_id, connection_id, title, username, last_message_at)
           VALUES(?, ?, ?, ?, ?)
           ON CONFLICT(chat_id) DO UPDATE SET connection_id=excluded.connection_id,
           title=excluded.title, username=excluded.username,
           last_message_at=MAX(chats.last_message_at, excluded.last_message_at)""",
        (chat_id, connection_id, _chat_title(chat), str(chat.get("username") or ""), message.get("date", 0)),
    )
    connection.execute(
        """INSERT OR REPLACE INTO messages
           (connection_id, chat_id, message_id, date, sender_id, outgoing, text)
           VALUES(?, ?, ?, ?, ?, ?, ?)""",
        (
            connection_id, chat_id, message_id, message.get("date", 0), sender.get("id"),
            int(bool(message.get("sender_business_bot"))),
            str(message.get("text") or message.get("caption") or "")[:8000],
        ),
    )


def _sync_updates_sync() -> int:
    with _database() as connection:
        row = connection.execute("SELECT value FROM meta WHERE key='update_offset'").fetchone()
        offset = int(row["value"]) if row else 0
        updates = _api("getUpdates", {
            "offset": offset,
            "timeout": 0,
            "limit": 100,
            "allowed_updates": [
                "business_connection", "business_message",
                "edited_business_message", "deleted_business_messages",
            ],
        }) or []
        for update in updates:
            _store_update(connection, update)
            offset = max(offset, int(update.get("update_id", 0)) + 1)
        if updates:
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('update_offset', ?)",
                (str(offset),),
            )
        return len(updates)


async def _sync_updates() -> int:
    return await asyncio.to_thread(_sync_updates_sync)


def _resolve_chat(connection: sqlite3.Connection, query: str) -> sqlite3.Row:
    needle = " ".join(str(query).casefold().split()).lstrip("@")
    if not needle:
        raise ValueError("Chat name is empty.")
    rows = connection.execute("SELECT * FROM chats ORDER BY last_message_at DESC").fetchall()
    exact = [row for row in rows if needle in {row["title"].casefold(), row["username"].casefold()}]
    partial = [row for row in rows if needle in row["title"].casefold() or needle in row["username"].casefold()]
    matches = exact or partial
    if not matches:
        raise LookupError(
            f"Telegram Business chat '{query}' has not been observed yet. "
            "Ask that person to send a message after the bot is connected."
        )
    return matches[0]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def get_status() -> dict[str, Any]:
    """Validate the Bot token and report connected Telegram Business accounts."""
    me, update_count = await asyncio.gather(
        asyncio.to_thread(_api, "getMe"),
        _sync_updates(),
    )
    with _database() as connection:
        connections = [dict(row) for row in connection.execute(
            "SELECT id, user_id, username, enabled FROM connections ORDER BY rowid DESC"
        )]
    return {"bot": me, "business_connections": connections, "new_updates": update_count}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def list_chats(query: str = "", limit: int = 30) -> dict[str, Any]:
    """List Telegram Business chats observed since the bot was connected."""
    await _sync_updates()
    clean = " ".join(str(query).casefold().split()).lstrip("@")
    bounded = max(1, min(100, int(limit)))
    with _database() as connection:
        rows = connection.execute("SELECT * FROM chats ORDER BY last_message_at DESC").fetchall()
    chats = [dict(row) for row in rows if not clean or clean in row["title"].casefold() or clean in row["username"].casefold()]
    return {"count": min(len(chats), bounded), "chats": chats[:bounded]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def read_messages(chat: str, limit: int = 20) -> dict[str, Any]:
    """Read locally cached messages received through the Business connection."""
    await _sync_updates()
    bounded = max(1, min(100, int(limit)))
    with _database() as connection:
        resolved = _resolve_chat(connection, chat)
        rows = connection.execute(
            """SELECT message_id, date, sender_id, outgoing, text FROM messages
               WHERE connection_id=? AND chat_id=? ORDER BY date DESC, message_id DESC LIMIT ?""",
            (resolved["connection_id"], resolved["chat_id"], bounded),
        ).fetchall()
    return {"chat": resolved["title"], "messages": [dict(row) for row in reversed(rows)]}


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True,
    )
)
async def send_message(chat: str, text: str) -> dict[str, Any]:
    """Send a message on behalf of the connected account. Requires confirmation."""
    clean_text = str(text).strip()
    if not clean_text:
        raise ValueError("Message text is empty.")
    if len(clean_text) > 4096:
        raise ValueError("Telegram message exceeds 4096 characters.")
    await _sync_updates()
    with _database() as connection:
        resolved = _resolve_chat(connection, chat)
    result = await asyncio.to_thread(
        _api,
        "sendMessage",
        {
            "business_connection_id": resolved["connection_id"],
            "chat_id": resolved["chat_id"],
            "text": clean_text,
        },
    )
    return {
        "sent": True,
        "chat": resolved["title"],
        "message_id": result.get("message_id") if isinstance(result, dict) else None,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
