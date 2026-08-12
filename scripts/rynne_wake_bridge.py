"""Tiny always-on bridge that starts Rynne after an authenticated cloud wake signal."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import ctypes
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.integrations.cloud_remote import CloudRemoteError, RynneCloudRemoteClient


_MUTEX_HANDLE = None


def acquire_single_instance(*, timeout_seconds: float = 5.0) -> bool:
    """Keep exactly one poller alive per signed-in Windows user."""
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    kernel32 = ctypes.windll.kernel32
    deadline = time.monotonic() + timeout_seconds
    while True:
        handle = kernel32.CreateMutexW(None, False, "Local\\RynneWakeBridge")
        if handle and kernel32.GetLastError() != 183:
            _MUTEX_HANDLE = handle
            return True
        if handle:
            kernel32.CloseHandle(handle)
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


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
    log_dir = Path(os.getenv("LOCALAPPDATA", str(ROOT))) / "ai.nova.desktop" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    launch_log = log_dir / "rynne-wake-launch.log"
    candidates = [
        Path(os.getenv("LOCALAPPDATA", "")) / "Rynne" / "Rynne.exe",
        Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Rynne" / "Rynne.exe",
    ]
    for executable in candidates:
        if executable.is_file():
            with launch_log.open("ab") as output:
                process = subprocess.Popen(
                    [str(executable)], stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                    close_fds=True,
                )
            time.sleep(2)
            if process.poll() is not None:
                logging.error("Installed Rynne exited during startup with code %s; log=%s", process.returncode, launch_log)
                continue
            return True
    dev_script = ROOT / "scripts" / "dev-desktop.ps1"
    if dev_script.is_file():
        with launch_log.open("ab") as output:
            process = subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(dev_script)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        time.sleep(3)
        if process.poll() is None:
            logging.info("Development runtime started with pid=%s; log=%s", process.pid, launch_log)
            return True
        logging.error("Development runtime exited with code %s; log=%s", process.returncode, launch_log)
    return False


def main() -> int:
    load_env(ROOT / ".env")
    log_dir = Path(os.getenv("LOCALAPPDATA", str(ROOT))) / "ai.nova.desktop" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "rynne-wake-bridge.log", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", force=True,
    )
    if not acquire_single_instance():
        logging.warning("Another wake bridge still owns the single-instance lock; exiting")
        return 0
    client = RynneCloudRemoteClient.from_env()
    if not client.configured:
        logging.error("Cloud remote is not configured; check URL, device ID and device token")
        return 2
    logging.info("Wake bridge started; device=%s url=%s", client.config.device_id, client.config.base_url)
    while True:
        try:
            if client.next_wake() and not rynne_running():
                logging.info("Cloud wake received; launch=%s", launch_rynne())
        except CloudRemoteError as exc:
            logging.warning("Cloud wake poll failed: %s", exc)
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
