"""Authorize Nova's local Telegram MCP session and update the local .env."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _upsert_env(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(values)
    updated: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in pending:
            updated.append(f"{key}={pending.pop(key)}")
        else:
            updated.append(line)
    if pending and updated and updated[-1].strip():
        updated.append("")
    updated.extend(f"{key}={value}" for key, value in pending.items())
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


async def _authorize(api_id: int, api_hash: str, phone: str, session_path: Path) -> None:
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise SystemExit(
            "Telethon is missing. Run: py -m pip install -r requirements.txt"
        ) from exc
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.start(phone=phone or None)
    me = await client.get_me()
    print(f"Telegram authorized: @{getattr(me, 'username', None) or me.id}")
    await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up Nova Telegram MCP")
    parser.add_argument("--api-id", type=int)
    parser.add_argument("--api-hash")
    parser.add_argument("--phone")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()

    api_id = args.api_id or int(input("Telegram API ID: ").strip())
    api_hash = args.api_hash or getpass.getpass("Telegram API hash: ").strip()
    phone = args.phone or input("Phone number (+...): ").strip()
    session_path = (
        Path(os.getenv("LOCALAPPDATA", Path.home()))
        / "Nova" / "telegram-mcp" / "nova"
    ).resolve()
    asyncio.run(_authorize(api_id, api_hash, phone, session_path))
    _upsert_env(
        args.env_file,
        {
            "NOVA_TELEGRAM_MCP_ENABLED": "true",
            "TELEGRAM_API_ID": str(api_id),
            "TELEGRAM_API_HASH": api_hash,
            "TELEGRAM_SESSION_PATH": str(session_path),
        },
    )
    print(f"Nova configuration updated: {args.env_file}")
    print("Restart Nova Core. Telegram MCP tools will be discovered automatically.")


if __name__ == "__main__":
    main()
