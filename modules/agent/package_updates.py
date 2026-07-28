from __future__ import annotations

import asyncio
import importlib.metadata
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import requests
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from modules.domain.results import ToolResult
from modules.storage.database import Database


MAX_PACKAGE_WATCHES = 50
MAX_PYPI_RESPONSE_BYTES = 512 * 1024
PACKAGE_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)


def _request_pypi(package_name: str) -> str:
    response = requests.get(
        f"https://pypi.org/pypi/{package_name}/json",
        headers={"User-Agent": "NovaUpdateMonitor/1.0"},
        timeout=10,
        allow_redirects=False,
        stream=True,
    )
    try:
        if response.status_code != 200:
            raise ValueError(
                f"PyPI вернул HTTP {response.status_code}."
            )
        body = bytearray()
        for chunk in response.iter_content(chunk_size=32 * 1024):
            body.extend(chunk)
            if len(body) > MAX_PYPI_RESPONSE_BYTES:
                raise ValueError("Ответ PyPI превышает 512 КБ.")
        payload = json.loads(bytes(body))
        version = payload.get("info", {}).get("version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("PyPI не вернул последнюю версию.")
        Version(version)
        return version
    finally:
        response.close()


async def fetch_latest_version(package_name: str) -> str:
    return await asyncio.to_thread(
        _request_pypi,
        package_name,
    )


class PackageUpdateManager:
    def __init__(
        self,
        database: Database,
        *,
        fetcher: Callable[[str], Awaitable[str]] = fetch_latest_version,
        version_getter: Callable[
            [str],
            str,
        ] = importlib.metadata.version,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database = database
        self.fetcher = fetcher
        self.version_getter = version_getter
        self.clock = clock

    @staticmethod
    def normalize_package_name(package_name: str) -> str:
        candidate = package_name.strip()
        if not PACKAGE_NAME_PATTERN.fullmatch(candidate):
            raise ValueError("Некорректное имя Python-пакета.")
        return canonicalize_name(candidate)

    async def add_watch(
        self,
        package_name: str,
    ) -> ToolResult:
        try:
            normalized = self.normalize_package_name(package_name)
            installed = self.version_getter(normalized)
            Version(installed)
        except importlib.metadata.PackageNotFoundError:
            return ToolResult.failure(
                "PACKAGE_NOT_INSTALLED",
                f"Пакет '{package_name}' не установлен.",
            )
        except (InvalidVersion, ValueError) as exc:
            return ToolResult.failure(
                "INVALID_PACKAGE",
                str(exc),
            )

        existing = self.database.fetchone(
            """
            SELECT watch_id FROM package_update_watches
            WHERE package_name = ?
            """,
            (normalized,),
        )
        if existing is not None:
            return ToolResult.ok(
                "Обновления этого пакета уже отслеживаются.",
                data={
                    "watch_id": existing["watch_id"],
                    "package_name": normalized,
                },
            )

        count_row = self.database.fetchone(
            "SELECT COUNT(*) AS count FROM package_update_watches"
        )
        if (
            count_row is not None
            and int(count_row["count"]) >= MAX_PACKAGE_WATCHES
        ):
            return ToolResult.failure(
                "PACKAGE_WATCH_LIMIT",
                f"Достигнут лимит: {MAX_PACKAGE_WATCHES} пакетов.",
            )

        try:
            latest = await self.fetcher(normalized)
            Version(latest)
        except Exception as exc:
            return ToolResult.failure(
                "PYPI_CHECK_FAILED",
                f"Не удалось проверить PyPI: {exc}",
            )

        watch_id = f"package_{uuid.uuid4().hex}"
        now = self.clock()
        self.database.execute(
            """
            INSERT INTO package_update_watches (
                watch_id, package_name, installed_version,
                latest_version, checked_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                watch_id,
                normalized,
                installed,
                latest,
                now,
                now,
            ),
        )
        self.database.commit()
        return ToolResult.ok(
            "Контроль обновлений пакета включён.",
            data={
                "watch_id": watch_id,
                "package_name": normalized,
                "installed_version": installed,
                "latest_version": latest,
                "update_available": (
                    Version(latest) > Version(installed)
                ),
            },
        )

    async def poll(self) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT watch_id, package_name
            FROM package_update_watches
            WHERE enabled = 1
            LIMIT 50
            """
        )
        statuses: list[dict[str, Any]] = []
        for row in rows:
            error: str | None = None
            installed: str | None = None
            latest: str | None = None
            update_available = False
            try:
                installed = self.version_getter(
                    str(row["package_name"])
                )
                latest = await self.fetcher(
                    str(row["package_name"])
                )
                update_available = (
                    Version(latest) > Version(installed)
                )
            except Exception as exc:
                error = str(exc)[:500]

            self.database.execute(
                """
                UPDATE package_update_watches
                SET installed_version = COALESCE(?, installed_version),
                    latest_version = COALESCE(?, latest_version),
                    checked_at = ?,
                    last_error = ?
                WHERE watch_id = ?
                """,
                (
                    installed,
                    latest,
                    self.clock(),
                    error,
                    row["watch_id"],
                ),
            )
            statuses.append(
                {
                    **row,
                    "installed_version": installed,
                    "latest_version": latest,
                    "update_available": update_available,
                    "error": error,
                }
            )
        self.database.commit()
        return statuses

    def list_watches(self) -> ToolResult:
        rows = self.database.fetchall(
            """
            SELECT watch_id, package_name, installed_version,
                   latest_version, checked_at, last_error
            FROM package_update_watches
            WHERE enabled = 1
            ORDER BY created_at DESC
            """
        )
        return ToolResult.ok(
            f"Отслеживается обновлений пакетов: {len(rows)}.",
            data={"count": len(rows), "watches": rows},
        )

    def remove_watch(self, watch_id: str) -> ToolResult:
        cursor = self.database.execute(
            "DELETE FROM package_update_watches WHERE watch_id = ?",
            (watch_id,),
        )
        self.database.commit()
        if cursor.rowcount == 0:
            return ToolResult.failure(
                "PACKAGE_WATCH_NOT_FOUND",
                f"Подписка '{watch_id}' не найдена.",
            )
        return ToolResult.ok(
            f"Подписка '{watch_id}' удалена.",
        )
