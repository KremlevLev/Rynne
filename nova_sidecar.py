"""
Entry point for Rynne Core when launched by the Tauri desktop shell.

Human-readable output is redirected to stderr before importing the app. The
original stdout remains reserved for JSON Lines protocol events.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback


def run() -> int:
    if "--telegram-bot-mcp-server" in sys.argv:
        for stream in (sys.stdout, sys.stdin, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(
                    encoding="utf-8",
                    errors="replace",
                    newline="\n",
                    write_through=True,
                )
        from integrations.telegram_bot_mcp.server import mcp

        mcp.run(transport="stdio")
        return 0

    if "--telegram-mcp-server" in sys.argv:
        # In an installed build the same bundled executable acts as a separate
        # stdio MCP process. Keep stdout untouched: it carries MCP frames.
        for stream in (sys.stdout, sys.stdin, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(
                    encoding="utf-8",
                    errors="replace",
                    newline="\n",
                    write_through=True,
                )
        from integrations.telegram_mcp.server import mcp

        mcp.run(transport="stdio")
        return 0

    protocol_stdout = sys.stdout
    for stream in (
        protocol_stdout,
        sys.stdin,
        sys.stderr,
    ):
        if not hasattr(stream, "reconfigure"):
            continue
        stream.reconfigure(
            encoding="utf-8",
            errors="replace",
            newline="\n",
            write_through=True,
        )
    sys.stdout = sys.stderr
    sys.__stdout__ = protocol_stdout

    os.environ["NOVA_DESKTOP_UI"] = "true"
    os.environ["NOVA_DESKTOP_TRANSPORT"] = "stdio"
    os.environ["NOVA_PREMIUM_UI"] = "false"

    try:
        from main import async_main

        asyncio.run(async_main())
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
