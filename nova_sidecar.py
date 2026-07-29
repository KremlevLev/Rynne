"""
Entry point for Nova Core when launched by the Tauri desktop shell.

Human-readable output is redirected to stderr before importing the app. The
original stdout remains reserved for JSON Lines protocol events.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback


def run() -> int:
    protocol_stdout = sys.stdout
    sys.stdout = sys.stderr

    os.environ["NOVA_DESKTOP_UI"] = "true"
    os.environ["NOVA_DESKTOP_TRANSPORT"] = "stdio"
    os.environ["NOVA_PREMIUM_UI"] = "false"

    # Some embedded Python launchers do not populate __stdout__.
    if sys.__stdout__ is None:
        sys.__stdout__ = protocol_stdout

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
