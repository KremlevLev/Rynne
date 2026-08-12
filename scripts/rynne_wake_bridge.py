"""Tiny always-on bridge that starts Rynne after an authenticated cloud wake signal."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.integrations.cloud_remote import CloudRemoteError, RynneCloudRemoteClient


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def rynne_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
    )
    names = result.stdout.casefold()
    return "rynne.exe" in names or "rynne-desktop.exe" in names


def launch_rynne() -> bool:
    candidates = [
        Path(os.getenv("LOCALAPPDATA", "")) / "Rynne" / "Rynne.exe",
        Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Rynne" / "Rynne.exe",
        ROOT / "apps" / "desktop" / "src-tauri" / "target" / "debug" / "rynne-desktop.exe",
    ]
    for executable in candidates:
        if executable.is_file():
            subprocess.Popen([str(executable)], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            return True
    dev_script = ROOT / "scripts" / "dev-desktop.ps1"
    if dev_script.is_file():
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(dev_script)],
            cwd=ROOT,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        return True
    return False


def main() -> int:
    load_env(ROOT / ".env")
    client = RynneCloudRemoteClient.from_env()
    if not client.configured:
        return 2
    log_dir = Path(os.getenv("LOCALAPPDATA", str(ROOT))) / "ai.nova.desktop" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / "rynne-wake-bridge.log", level=logging.INFO)
    while True:
        try:
            if client.next_wake() and not rynne_running():
                logging.info("Cloud wake received; launch=%s", launch_rynne())
        except CloudRemoteError as exc:
            logging.warning("Cloud wake poll failed: %s", exc)
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
