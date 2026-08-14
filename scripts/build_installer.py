"""Build the headless Rynne Core consumed by the Tauri desktop installer.

The Tauri CLI calls this script from ``beforeBuildCommand``.  It deliberately
builds an ``onedir`` application: Rynne imports large native packages such as
Torch, and extracting a PyInstaller ``onefile`` archive on every launch makes
desktop startup needlessly slow.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path


def configure_console_output() -> None:
    """Keep build logs writable on Windows runners with a non-UTF-8 locale."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


configure_console_output()


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TAURI_ROOT = PROJECT_ROOT / "apps" / "desktop" / "src-tauri"
CORE_RESOURCE_DIR = TAURI_ROOT / "resources" / "rynne-core"
CORE_BUILD_MANIFEST = TAURI_ROOT / "resources" / "rynne-core.build.json"
WAKE_RESOURCE_DIR = TAURI_ROOT / "resources" / "rynne-wake"
PYINSTALLER_ROOT = PROJECT_ROOT / "build" / "pyinstaller"
CORE_ENTRY_POINT = PROJECT_ROOT / "nova_sidecar.py"
WAKE_ENTRY_POINT = PROJECT_ROOT / "scripts" / "rynne_wake_bridge.py"
BUILD_RECIPE_VERSION = 6
CORE_REQUIRED_RUNTIME_ASSETS = (
    Path("_internal") / "rfc3987_syntax" / "syntax_rfc3987.lark",
)


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


def resolve_package_asset(package: str, relative_path: str) -> Path | None:
    """Resolve optional package data explicitly when that package is installed."""
    spec = importlib.util.find_spec(package)
    if spec is None:
        return None

    roots = [Path(path) for path in (spec.submodule_search_locations or [])]
    if spec.origin:
        roots.append(Path(spec.origin).parent)
    for root in roots:
        asset = root / relative_path
        if asset.is_file():
            return asset
    raise RuntimeError(
        f"Required package asset is unavailable: {package}/{relative_path}"
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
        *sorted((PROJECT_ROOT / "integrations").rglob("*.py")),
        *sorted((PROJECT_ROOT / "data" / "skills").rglob("*.md")),
    ]
    for path in sources:
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def core_is_current(fingerprint: str) -> bool:
    executable = CORE_RESOURCE_DIR / "rynne-core.exe"
    if not executable.is_file() or not CORE_BUILD_MANIFEST.is_file():
        return False
    try:
        manifest = json.loads(CORE_BUILD_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return manifest.get("source_fingerprint") == fingerprint


def stamp_core(fingerprint: str) -> None:
    if not (CORE_RESOURCE_DIR / "rynne-core.exe").is_file():
        raise RuntimeError("Cannot stamp a missing rynne-core.exe")
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
    executable = CORE_RESOURCE_DIR / "rynne-core.exe"
    if not force and core_is_current(fingerprint):
        print(f"Rynne Core не изменился, используется cache: {executable}")
        return executable

    ensure_pyinstaller()
    clean_core_output()
    PYINSTALLER_ROOT.mkdir(parents=True, exist_ok=True)
    rfc3987_grammar = resolve_package_asset(
        "rfc3987_syntax",
        "syntax_rfc3987.lark",
    )
    rfc3987_data_args = (
        ["--add-data", f"{rfc3987_grammar};rfc3987_syntax"]
        if rfc3987_grammar is not None
        else []
    )

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name",
        "rynne-core",
        "--distpath",
        str(CORE_RESOURCE_DIR.parent),
        "--workpath",
        str(PYINSTALLER_ROOT / "work"),
        "--specpath",
        str(PYINSTALLER_ROOT),
        "--paths",
        str(PROJECT_ROOT),
        "--add-data",
        f"{PROJECT_ROOT / 'data' / 'skills'};data/skills",
        # ``mcp.server.fastmcp`` loads this grammar at runtime through
        # importlib.resources. PyInstaller discovers the Python package but
        # not its non-Python ``.lark`` file, so a packaged Telegram MCP server
        # otherwise fails only after installation.
        *rfc3987_data_args,
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
        "mcp.server.fastmcp",
        "--hidden-import",
        "telethon",
        "--hidden-import",
        "integrations.telegram_bot_mcp.server",
        "--hidden-import",
        "playwright.async_api",
        str(CORE_ENTRY_POINT),
    ]
    run(command)

    if not executable.is_file():
        raise RuntimeError(f"Core executable was not produced: {executable}")
    validate_core_runtime_assets(
        CORE_RESOURCE_DIR,
        required_assets=(
            CORE_REQUIRED_RUNTIME_ASSETS
            if rfc3987_grammar is not None
            else ()
        ),
    )
    stamp_core(fingerprint)
    (CORE_RESOURCE_DIR / ".gitkeep").touch()

    size_mb = sum(
        path.stat().st_size
        for path in CORE_RESOURCE_DIR.rglob("*")
        if path.is_file()
    ) / (1024 * 1024)
    print(
        f"\nRynne Core готов: {executable} ({size_mb:.1f} MiB on disk)",
        flush=True,
    )
    return executable


def validate_core_runtime_assets(
    core_dir: Path,
    *,
    required_assets: tuple[Path, ...] = CORE_REQUIRED_RUNTIME_ASSETS,
) -> None:
    """Fail the release build when lazily loaded package data is absent."""
    missing = [
        str(relative_path)
        for relative_path in required_assets
        if not (core_dir / relative_path).is_file()
    ]
    if missing:
        raise RuntimeError(
            "Packaged Core is missing required runtime assets: "
            + ", ".join(missing)
        )


def build_wake_bridge() -> Path:
    """Build the tiny always-on cloud poller shipped beside the desktop app."""
    executable = WAKE_RESOURCE_DIR / "rynne-wake-bridge.exe"
    if WAKE_RESOURCE_DIR.exists():
        shutil.rmtree(WAKE_RESOURCE_DIR)
    WAKE_RESOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        "rynne-wake-bridge",
        "--distpath",
        str(WAKE_RESOURCE_DIR),
        "--workpath",
        str(PYINSTALLER_ROOT / "wake-work"),
        "--specpath",
        str(PYINSTALLER_ROOT),
        "--paths",
        str(PROJECT_ROOT),
        "--exclude-module",
        "torch",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "playwright",
        "--exclude-module",
        "PySide6",
        str(WAKE_ENTRY_POINT),
    ]
    run(command)
    if not executable.is_file():
        raise RuntimeError(f"Wake bridge executable was not produced: {executable}")
    print(f"Rynne Wake Bridge ready: {executable}", flush=True)
    return executable


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the packaged Rynne Python Core for Tauri.",
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
    build_wake_bridge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
