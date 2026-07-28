from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from modules.domain.results import ToolResult
from modules.storage.database import Database


MAX_BACKUP_WATCHES = 50
MAX_SCANNED_FILES = 10_000


def latest_backup_mtime(path: Path) -> float | None:
    if path.is_file():
        return path.stat().st_mtime
    if not path.is_dir():
        return None

    latest: float | None = None
    scanned = 0
    for root, directories, files in os.walk(
        path,
        followlinks=False,
    ):
        root_path = Path(root)
        directories[:] = [
            name
            for name in directories
            if not (root_path / name).is_symlink()
        ]
        for name in files:
            scanned += 1
            if scanned > MAX_SCANNED_FILES:
                raise ValueError(
                    "Папка содержит больше 10 000 файлов."
                )
            candidate = root_path / name
            if candidate.is_symlink():
                continue
            try:
                modified = candidate.stat().st_mtime
            except OSError:
                continue
            latest = (
                modified
                if latest is None
                else max(latest, modified)
            )
    return latest


class BackupWatchManager:
    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database = database
        self.clock = clock

    def add_watch(
        self,
        path: str,
        max_age_hours: float = 24.0,
        label: str = "",
    ) -> ToolResult:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            return ToolResult.failure(
                "BACKUP_PATH_NOT_FOUND",
                f"Путь резервной копии не найден: {resolved}",
            )
        if not 0.1 <= float(max_age_hours) <= 8760:
            return ToolResult.failure(
                "INVALID_BACKUP_MAX_AGE",
                "Допустимый возраст должен быть от 0.1 до 8760 часов.",
            )

        existing = self.database.fetchone(
            "SELECT watch_id FROM backup_watches WHERE path = ?",
            (str(resolved),),
        )
        if existing is not None:
            return ToolResult.ok(
                "Этот путь уже отслеживается.",
                data={
                    "watch_id": existing["watch_id"],
                    "path": str(resolved),
                },
            )

        count_row = self.database.fetchone(
            "SELECT COUNT(*) AS count FROM backup_watches"
        )
        if (
            count_row is not None
            and int(count_row["count"]) >= MAX_BACKUP_WATCHES
        ):
            return ToolResult.failure(
                "BACKUP_WATCH_LIMIT",
                f"Достигнут лимит: {MAX_BACKUP_WATCHES} подписок.",
            )

        watch_id = f"backup_{uuid.uuid4().hex}"
        self.database.execute(
            """
            INSERT INTO backup_watches (
                watch_id, path, label, max_age_seconds, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                watch_id,
                str(resolved),
                label.strip()[:200],
                float(max_age_hours) * 3600,
                self.clock(),
            ),
        )
        self.database.commit()
        return ToolResult.ok(
            "Контроль резервной копии включён.",
            data={
                "watch_id": watch_id,
                "path": str(resolved),
                "label": label.strip()[:200],
                "max_age_hours": float(max_age_hours),
            },
        )

    async def poll(self) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT watch_id, path, label, max_age_seconds
            FROM backup_watches
            WHERE enabled = 1
            LIMIT 50
            """
        )
        statuses: list[dict[str, Any]] = []
        now = self.clock()
        for row in rows:
            error: str | None = None
            try:
                latest_mtime = await asyncio.to_thread(
                    latest_backup_mtime,
                    Path(str(row["path"])),
                )
            except Exception as exc:
                latest_mtime = None
                error = str(exc)[:500]

            age_seconds = (
                max(0.0, now - latest_mtime)
                if latest_mtime is not None
                else None
            )
            status = (
                "missing"
                if latest_mtime is None
                else (
                    "stale"
                    if age_seconds > float(row["max_age_seconds"])
                    else "healthy"
                )
            )
            self.database.execute(
                """
                UPDATE backup_watches
                SET checked_at = ?, last_error = ?
                WHERE watch_id = ?
                """,
                (now, error, row["watch_id"]),
            )
            statuses.append(
                {
                    **row,
                    "status": status,
                    "latest_mtime": latest_mtime,
                    "age_seconds": age_seconds,
                    "error": error,
                }
            )
        self.database.commit()
        return statuses

    def list_watches(self) -> ToolResult:
        rows = self.database.fetchall(
            """
            SELECT watch_id, path, label, max_age_seconds,
                   checked_at, last_error
            FROM backup_watches
            WHERE enabled = 1
            ORDER BY created_at DESC
            """
        )
        for row in rows:
            row["max_age_hours"] = (
                float(row.pop("max_age_seconds")) / 3600
            )
        return ToolResult.ok(
            f"Отслеживается резервных копий: {len(rows)}.",
            data={"count": len(rows), "watches": rows},
        )

    def remove_watch(self, watch_id: str) -> ToolResult:
        cursor = self.database.execute(
            "DELETE FROM backup_watches WHERE watch_id = ?",
            (watch_id,),
        )
        self.database.commit()
        if cursor.rowcount == 0:
            return ToolResult.failure(
                "BACKUP_WATCH_NOT_FOUND",
                f"Подписка '{watch_id}' не найдена.",
            )
        return ToolResult.ok(
            f"Подписка '{watch_id}' удалена.",
        )
