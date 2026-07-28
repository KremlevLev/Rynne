from __future__ import annotations

import asyncio
import ctypes
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import psutil

from modules.input_hub.models import UserRequest


logger = logging.getLogger("WorkspaceContext")

PROJECT_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "requirements.txt",
    "*.sln",
    "*.code-workspace",
)
WINDOWS_PATH_PATTERN = re.compile(
    r"(?<!\w)([A-Za-z]:\\(?:[^<>:\"/\\|?*\r\n]+\\)*"
    r"[^<>:\"/\\|?*\r\n]*)"
)
CONTEXT_WORDS = (
    "проект",
    "репозитор",
    "workspace",
    "здесь",
    "тут",
    "этот",
    "тест",
    "diff",
    "git",
    "файл",
)


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    path: Path
    project_name: str
    source: str
    active_window_title: str | None = None
    process_name: str | None = None

    def to_metadata(self) -> dict[str, str]:
        metadata = {
            "workspace_path": str(self.path),
            "workspace_name": self.project_name,
            "workspace_source": self.source,
        }
        if self.active_window_title:
            metadata["active_window_title"] = self.active_window_title
        if self.process_name:
            metadata["active_process_name"] = self.process_name
        return metadata


class WorkspaceContextResolver:
    """Finds and remembers the project the user is currently working in."""

    def __init__(
        self,
        *,
        foreground_provider: (
            Callable[[], tuple[int, str] | None] | None
        ) = None,
        process_provider: (
            Callable[[int], object] | None
        ) = None,
    ) -> None:
        self._foreground_provider = (
            foreground_provider
            or self._get_foreground_window
        )
        self._process_provider = (
            process_provider or psutil.Process
        )
        self._lock = threading.Lock()
        self._last_snapshot: WorkspaceSnapshot | None = None

    @staticmethod
    def _get_foreground_window() -> tuple[int, str] | None:
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(
                hwnd,
                ctypes.byref(pid),
            )
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(
                max(1, length + 1)
            )
            user32.GetWindowTextW(
                hwnd,
                buffer,
                len(buffer),
            )
            return int(pid.value), buffer.value.strip()
        except Exception:
            return None

    @staticmethod
    def _marker_score(path: Path) -> int:
        score = 0
        for marker in PROJECT_MARKERS:
            try:
                if "*" in marker:
                    if any(path.glob(marker)):
                        score += 3
                elif (path / marker).exists():
                    score += 10 if marker == ".git" else 3
            except OSError:
                continue
        return score

    @classmethod
    def find_project_root(
        cls,
        candidate: str | Path,
        *,
        require_marker: bool = True,
    ) -> Path | None:
        try:
            path = Path(candidate).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        if path.is_file():
            path = path.parent
        if not path.is_dir():
            return None

        for current in (path, *path.parents):
            if cls._marker_score(current):
                return current
        return None if require_marker else path

    @staticmethod
    def _safe_process_value(
        process: object,
        attribute: str,
    ) -> str | None:
        try:
            value = getattr(process, attribute)()
        except Exception:
            return None
        clean = str(value or "").strip()
        return clean or None

    def _processes_for_foreground(
        self,
        process: object,
    ) -> Iterable[object]:
        yield process
        try:
            children = process.children(recursive=True)
        except Exception:
            children = []
        yield from reversed(children)

    @staticmethod
    def _is_nova_window(
        title: str,
        process_name: str | None,
    ) -> bool:
        lowered_title = title.casefold()
        lowered_process = (process_name or "").casefold()
        return (
            "nova" in lowered_title
            and lowered_process in {
                "nova.exe",
                "python.exe",
                "pythonw.exe",
            }
        )

    def observe_foreground(self) -> WorkspaceSnapshot | None:
        foreground = self._foreground_provider()
        if foreground is None:
            return None
        pid, title = foreground

        try:
            foreground_process = self._process_provider(pid)
        except Exception:
            return None

        foreground_name = self._safe_process_value(
            foreground_process,
            "name",
        )
        if self._is_nova_window(title, foreground_name):
            return None

        candidates: list[tuple[int, Path, str | None]] = []
        for process in self._processes_for_foreground(
            foreground_process
        ):
            cwd = self._safe_process_value(process, "cwd")
            if not cwd:
                continue
            root = self.find_project_root(cwd)
            if root is None:
                continue
            candidates.append(
                (
                    self._marker_score(root),
                    root,
                    self._safe_process_value(process, "name"),
                )
            )

        if not candidates:
            return None
        _, path, process_name = max(
            candidates,
            key=lambda item: item[0],
        )
        snapshot = WorkspaceSnapshot(
            path=path,
            project_name=path.name,
            source="active_window",
            active_window_title=title or None,
            process_name=process_name or foreground_name,
        )
        with self._lock:
            self._last_snapshot = snapshot
        return snapshot

    def _explicit_snapshot(
        self,
        request: UserRequest,
    ) -> WorkspaceSnapshot | None:
        explicit = request.metadata.get("workspace_path")
        if explicit:
            root = self.find_project_root(
                str(explicit),
                require_marker=False,
            )
            if root is not None:
                return WorkspaceSnapshot(
                    path=root,
                    project_name=root.name,
                    source="request_metadata",
                    active_window_title=request.active_window_title,
                )

        for attachment in request.attachments:
            if not attachment.path:
                continue
            root = self.find_project_root(attachment.path)
            if root is not None:
                return WorkspaceSnapshot(
                    path=root,
                    project_name=root.name,
                    source="attachment",
                    active_window_title=request.active_window_title,
                )

        for match in WINDOWS_PATH_PATTERN.finditer(request.text):
            root = self.find_project_root(
                match.group(1).rstrip(" .,!?:;"),
                require_marker=False,
            )
            if root is not None:
                return WorkspaceSnapshot(
                    path=root,
                    project_name=root.name,
                    source="request_path",
                    active_window_title=request.active_window_title,
                )
        return None

    def resolve(
        self,
        request: UserRequest,
    ) -> WorkspaceSnapshot | None:
        snapshot = self._explicit_snapshot(request)
        if snapshot is None:
            snapshot = self.observe_foreground()
        if snapshot is None:
            with self._lock:
                cached = self._last_snapshot
            if cached is not None and (
                request.source.value != "background_task"
                or any(
                    word in request.text.casefold()
                    for word in CONTEXT_WORDS
                )
            ):
                snapshot = WorkspaceSnapshot(
                    path=cached.path,
                    project_name=cached.project_name,
                    source="recent_workspace",
                    active_window_title=(
                        request.active_window_title
                        or cached.active_window_title
                    ),
                    process_name=cached.process_name,
                )
        return snapshot

    def enrich(self, request: UserRequest) -> WorkspaceSnapshot | None:
        snapshot = self.resolve(request)
        if snapshot is None:
            return None

        request.metadata.update(snapshot.to_metadata())
        if (
            not request.active_window_title
            and snapshot.active_window_title
        ):
            request.active_window_title = snapshot.active_window_title
        with self._lock:
            self._last_snapshot = snapshot
        return snapshot

    async def monitor(
        self,
        shutdown_event: asyncio.Event,
        *,
        interval_seconds: float = 1.0,
    ) -> None:
        """Keeps the last real project before Nova's own UI takes focus."""
        while not shutdown_event.is_set():
            await asyncio.to_thread(
                self.observe_foreground
            )
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=max(0.25, interval_seconds),
                )
            except asyncio.TimeoutError:
                pass
