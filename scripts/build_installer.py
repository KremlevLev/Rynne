"""Build the headless Nova Core consumed by the Tauri desktop installer.

The Tauri CLI calls this script from ``beforeBuildCommand``.  It deliberately
builds an ``onedir`` application: Nova imports large native packages such as
Torch, and extracting a PyInstaller ``onefile`` archive on every launch makes
desktop startup needlessly slow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TAURI_ROOT = PROJECT_ROOT / "apps" / "desktop" / "src-tauri"
CORE_RESOURCE_DIR = TAURI_ROOT / "resources" / "nova-core"
CORE_BUILD_MANIFEST = TAURI_ROOT / "resources" / "nova-core.build.json"
PYINSTALLER_ROOT = PROJECT_ROOT / "build" / "pyinstaller"
CORE_ENTRY_POINT = PROJECT_ROOT / "nova_sidecar.py"
BUILD_RECIPE_VERSION = 1


def run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> None:
    printable = subprocess.list2cmdline(command)
    print(f"\n> {printable}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def ensure_pyinstaller() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            "PyInstaller не установлен. Выполни: "
            "python -m pip install pyinstaller"
        )
    print(
        f"PyInstaller {result.stdout.strip()} · Python {sys.version.split()[0]}",
        flush=True,
    )


def clean_core_output() -> None:
    resolved = CORE_RESOURCE_DIR.resolve()
    expected_parent = (TAURI_ROOT / "resources").resolve()
    if resolved.parent != expected_parent:
        raise RuntimeError(f"Unsafe build directory: {resolved}")

    if CORE_RESOURCE_DIR.exists():
        shutil.rmtree(CORE_RESOURCE_DIR)
    CORE_RESOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    CORE_RESOURCE_DIR.mkdir()
    (CORE_RESOURCE_DIR / ".gitkeep").touch()
    CORE_BUILD_MANIFEST.unlink(missing_ok=True)


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(f"recipe={BUILD_RECIPE_VERSION}\n".encode())
    digest.update(f"python={sys.version}\n".encode())

    sources = [
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "nova_sidecar.py",
        PROJECT_ROOT / "requirements.txt",
        *sorted((PROJECT_ROOT / "core").rglob("*.py")),
        *sorted((PROJECT_ROOT / "modules").rglob("*.py")),
    ]
    for path in sources:
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def core_is_current(fingerprint: str) -> bool:
    executable = CORE_RESOURCE_DIR / "nova-core.exe"
    if not executable.is_file() or not CORE_BUILD_MANIFEST.is_file():
        return False
    try:
        manifest = json.loads(CORE_BUILD_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return manifest.get("source_fingerprint") == fingerprint


def stamp_core(fingerprint: str) -> None:
    if not (CORE_RESOURCE_DIR / "nova-core.exe").is_file():
        raise RuntimeError("Cannot stamp a missing nova-core.exe")
    CORE_BUILD_MANIFEST.write_text(
        json.dumps(
            {
                "source_fingerprint": fingerprint,
                "python": sys.version.split()[0],
                "recipe": BUILD_RECIPE_VERSION,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_core(*, force: bool = False) -> Path:
    fingerprint = source_fingerprint()
    executable = CORE_RESOURCE_DIR / "nova-core.exe"
    if not force and core_is_current(fingerprint):
        print(f"Nova Core не изменился, используется cache: {executable}")
        return executable

    ensure_pyinstaller()
    clean_core_output()
    PYINSTALLER_ROOT.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name",
        "nova-core",
        "--distpath",
        str(CORE_RESOURCE_DIR.parent),
        "--workpath",
        str(PYINSTALLER_ROOT / "work"),
        "--specpath",
        str(PYINSTALLER_ROOT),
        "--paths",
        str(PROJECT_ROOT),
        # The Tauri process owns the UI. These legacy presentation packages
        # must not add hundreds of megabytes to the headless Core.
        "--exclude-module",
        "PySide6",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "IPython",
        # Runtime-facing modules whose imports may be resolved lazily.
        "--hidden-import",
        "mcp.client.stdio",
        "--hidden-import",
        "mcp.client.sse",
        "--hidden-import",
        "playwright.async_api",
        str(CORE_ENTRY_POINT),
    ]
    run(command)

    if not executable.is_file():
        raise RuntimeError(f"Core executable was not produced: {executable}")
    stamp_core(fingerprint)
    (CORE_RESOURCE_DIR / ".gitkeep").touch()

    size_mb = sum(
        path.stat().st_size
        for path in CORE_RESOURCE_DIR.rglob("*")
        if path.is_file()
    ) / (1024 * 1024)
    print(
        f"\nNova Core готов: {executable} ({size_mb:.1f} MiB on disk)",
        flush=True,
    )
    return executable


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the packaged Nova Python Core for Tauri.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the generated Core without rebuilding it.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild Core even when its source fingerprint is unchanged.",
    )
    parser.add_argument(
        "--stamp-existing",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if args.clean:
        clean_core_output()
        print(f"Удалено: {CORE_RESOURCE_DIR}")
        return 0

    if args.stamp_existing:
        stamp_core(source_fingerprint())
        print(f"Build manifest записан: {CORE_BUILD_MANIFEST}")
        return 0

    build_core(force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
