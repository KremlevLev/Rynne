"""Tiny always-on bridge that starts Rynne after an authenticated cloud wake signal."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import ctypes
from pathlib import Path
from typing import Iterable

try:
    import winreg
except ImportError:  # pragma: no cover - Windows-only discovery
    winreg = None


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.integrations.cloud_remote import CloudRemoteError, RynneCloudRemoteClient


_MUTEX_HANDLE = None


def installation_root() -> Path:
    """Return the installer directory when frozen, otherwise the repository."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return ROOT


def _clean_registry_path(value: str) -> Path | None:
    raw = str(value or "").strip().strip('"')
    if not raw:
        return None
    # DisplayIcon may contain a resource suffix such as `app.exe,0`.
    raw = raw.rsplit(",", 1)[0].strip().strip('"')
    return Path(os.path.expandvars(raw))


def _registered_executables() -> Iterable[Path]:
    if os.name != "nt" or winreg is None:
        return []
    found: list[Path] = []
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    views = (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0))
    for root in roots:
        for view in views:
            try:
                parent = winreg.OpenKey(root, uninstall, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with parent:
                for index in range(winreg.QueryInfoKey(parent)[0]):
                    try:
                        child = winreg.OpenKey(parent, winreg.EnumKey(parent, index))
                        with child:
                            name = str(winreg.QueryValueEx(child, "DisplayName")[0]).strip()
                            if name.casefold() != "rynne":
                                continue
                            try:
                                icon = _clean_registry_path(winreg.QueryValueEx(child, "DisplayIcon")[0])
                            except OSError:
                                icon = None
                            if icon is not None:
                                found.append(icon)
                            try:
                                location = _clean_registry_path(winreg.QueryValueEx(child, "InstallLocation")[0])
                            except OSError:
                                location = None
                            if location is not None:
                                found.extend((location / "rynne-desktop.exe", location / "Rynne.exe"))
                    except OSError:
                        continue
    return found


def installed_executable_candidates() -> list[Path]:
    """Production binaries only, ordered from explicit to discovered paths."""
    local = Path(os.getenv("LOCALAPPDATA", ""))
    program_files = Path(os.getenv("ProgramFiles", ""))
    explicit = _clean_registry_path(os.getenv("RYNNE_DESKTOP_EXE", ""))
    candidates = [
        explicit,
        installation_root() / "rynne-desktop.exe",
        installation_root() / "Rynne.exe",
        local / "Rynne" / "rynne-desktop.exe",
        local / "Rynne" / "Rynne.exe",
        local / "Programs" / "Rynne" / "rynne-desktop.exe",
        local / "Programs" / "Rynne" / "Rynne.exe",
        program_files / "Rynne" / "rynne-desktop.exe",
        *_registered_executables(),
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        if path is None:
            continue
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


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


def load_env(path: Path, *, overwrite: bool = False) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        name = key.strip()
        value = value.strip().strip('"').strip("'")
        if overwrite or name not in os.environ:
            os.environ[name] = value


def load_runtime_env() -> None:
    for env_path in (
        Path(os.getenv("APPDATA", "")) / "ai.nova.desktop" / ".env",
        Path(os.getenv("LOCALAPPDATA", "")) / "ai.nova.desktop" / ".env",
        installation_root() / ".env",
        ROOT / ".env",
    ):
        load_env(env_path, overwrite=True)


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
    for executable in installed_executable_candidates():
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
    # Never surprise a normal user with Vite + Cargo. Developers can opt in.
    dev_script = ROOT / "scripts" / "dev-desktop.ps1"
    if os.getenv("RYNNE_WAKE_ALLOW_DEV", "").strip() == "1" and dev_script.is_file():
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
    logging.error("Installed Rynne executable was not found; checked=%s", [str(item) for item in installed_executable_candidates()])
    return False


def main() -> int:
    load_runtime_env()
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
    logging.info("Wake bridge started")
    while True:
        if not client.configured:
            logging.info("Cloud remote is not configured yet; waiting for desktop settings")
            time.sleep(10)
            load_runtime_env()
            client = RynneCloudRemoteClient.from_env()
            continue
        try:
            if client.next_wake() and not rynne_running():
                logging.info("Cloud wake received; launch=%s", launch_rynne())
        except CloudRemoteError as exc:
            logging.warning("Cloud wake poll failed: %s", exc)
            load_runtime_env()
            client = RynneCloudRemoteClient.from_env()
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
