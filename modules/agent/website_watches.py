from __future__ import annotations

import asyncio
import hashlib
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from modules.browser.manager import (
    validate_browser_url,
    validate_resolved_host,
)
from modules.domain.results import ToolResult
from modules.storage.database import Database


MAX_WEBSITE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_WEBSITE_WATCHES = 50


async def validate_public_url(
    url: str,
) -> tuple[bool, str | None, str | None]:
    valid, normalized, error = validate_browser_url(url)
    if not valid or normalized is None:
        return False, None, error
    resolved, resolution_error = await validate_resolved_host(
        normalized
    )
    if not resolved:
        return False, None, resolution_error
    return True, normalized, None


def _request_page(url: str) -> tuple[int, dict[str, str], bytes]:
    with requests.get(
        url,
        headers={"User-Agent": "NovaWebsiteMonitor/1.0"},
        timeout=10,
        allow_redirects=False,
        stream=True,
    ) as response:
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_WEBSITE_BYTES:
                raise ValueError(
                    "Страница превышает лимит мониторинга 2 МБ."
                )
        headers = {
            key.lower(): value
            for key, value in response.headers.items()
        }
        return response.status_code, headers, bytes(body)


def _normalize_content(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    for node in soup(
        ["script", "style", "noscript", "svg", "template"]
    ):
        node.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


async def fetch_website_content(url: str) -> str:
    current = url
    for redirect_index in range(MAX_REDIRECTS + 1):
        valid, normalized, error = await validate_public_url(current)
        if not valid or normalized is None:
            raise ValueError(error or "URL заблокирован.")

        status, headers, body = await asyncio.to_thread(
            _request_page,
            normalized,
        )
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location:
                raise ValueError("Redirect не содержит Location.")
            if redirect_index >= MAX_REDIRECTS:
                raise ValueError("Слишком много redirect.")
            current = urljoin(normalized, location)
            continue
        if status < 200 or status >= 300:
            raise ValueError(f"Сайт вернул HTTP {status}.")

        content_type = headers.get("content-type", "").lower()
        if content_type and not any(
            marker in content_type
            for marker in ("text/", "json", "xml", "html")
        ):
            raise ValueError(
                f"Неподдерживаемый Content-Type: {content_type}."
            )
        return _normalize_content(body)

    raise ValueError("Не удалось загрузить страницу.")


class WebsiteWatchManager:
    def __init__(
        self,
        database: Database,
        *,
        fetcher: Callable[[str], Awaitable[str]] = fetch_website_content,
        validator: Callable[
            [str],
            Awaitable[tuple[bool, str | None, str | None]],
        ] = validate_public_url,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database = database
        self.fetcher = fetcher
        self.validator = validator
        self.clock = clock

    async def add_watch(
        self,
        url: str,
        label: str = "",
    ) -> ToolResult:
        valid, normalized, error = await self.validator(url)
        if not valid or normalized is None:
            return ToolResult.failure(
                "WEBSITE_URL_BLOCKED",
                error or "URL заблокирован.",
            )

        existing = self.database.fetchone(
            "SELECT watch_id FROM website_watches WHERE url = ?",
            (normalized,),
        )
        if existing is not None:
            return ToolResult.ok(
                "Этот сайт уже отслеживается.",
                data={"watch_id": existing["watch_id"], "url": normalized},
            )

        count_row = self.database.fetchone(
            "SELECT COUNT(*) AS count FROM website_watches"
        )
        if (
            count_row is not None
            and int(count_row["count"]) >= MAX_WEBSITE_WATCHES
        ):
            return ToolResult.failure(
                "WEBSITE_WATCH_LIMIT",
                (
                    "Достигнут лимит подписок на сайты: "
                    f"{MAX_WEBSITE_WATCHES}."
                ),
            )

        try:
            content = await self.fetcher(normalized)
        except Exception as exc:
            return ToolResult.failure(
                "WEBSITE_BASELINE_FAILED",
                f"Не удалось получить baseline: {exc}",
            )

        watch_id = f"watch_{uuid.uuid4().hex}"
        now = self.clock()
        self.database.execute(
            """
            INSERT INTO website_watches (
                watch_id, url, label, content_hash,
                revision, notified_revision, checked_at, created_at
            ) VALUES (?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (
                watch_id,
                normalized,
                label.strip()[:200],
                hashlib.sha256(content.encode("utf-8")).hexdigest(),
                now,
                now,
            ),
        )
        self.database.commit()
        return ToolResult.ok(
            "Сайт добавлен в мониторинг.",
            data={
                "watch_id": watch_id,
                "url": normalized,
                "label": label.strip()[:200],
            },
        )

    async def poll(self) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT watch_id, url, label, content_hash, revision
            FROM website_watches
            WHERE enabled = 1
            LIMIT 50
            """
        )
        for row in rows:
            try:
                content = await self.fetcher(str(row["url"]))
                digest = hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest()
                changed = digest != row["content_hash"]
                self.database.execute(
                    """
                    UPDATE website_watches
                    SET content_hash = ?,
                        revision = revision + ?,
                        checked_at = ?,
                        last_error = NULL
                    WHERE watch_id = ?
                    """,
                    (
                        digest,
                        1 if changed else 0,
                        self.clock(),
                        row["watch_id"],
                    ),
                )
            except Exception as exc:
                self.database.execute(
                    """
                    UPDATE website_watches
                    SET checked_at = ?, last_error = ?
                    WHERE watch_id = ?
                    """,
                    (
                        self.clock(),
                        str(exc)[:500],
                        row["watch_id"],
                    ),
                )
        self.database.commit()
        return self.pending_changes()

    def pending_changes(self) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT watch_id, url, label, revision
            FROM website_watches
            WHERE enabled = 1
              AND revision > notified_revision
            """
        )
        pending: list[dict[str, Any]] = []
        for row in rows:
            source_key = (
                f"website:{row['watch_id']}:revision:{row['revision']}"
            )
            already_recorded = self.database.fetchone(
                """
                SELECT event_id FROM proactive_events
                WHERE source_key = ?
                """,
                (source_key,),
            )
            if already_recorded is not None:
                self.mark_notified(
                    str(row["watch_id"]),
                    int(row["revision"]),
                )
                continue
            pending.append(row)
        return pending

    def mark_notified(self, watch_id: str, revision: int) -> None:
        self.database.execute(
            """
            UPDATE website_watches
            SET notified_revision = MAX(notified_revision, ?)
            WHERE watch_id = ?
            """,
            (revision, watch_id),
        )
        self.database.commit()

    async def list_watches(self) -> ToolResult:
        rows = self.database.fetchall(
            """
            SELECT watch_id, url, label, revision, checked_at, last_error
            FROM website_watches
            WHERE enabled = 1
            ORDER BY created_at DESC
            """
        )
        return ToolResult.ok(
            f"Отслеживается сайтов: {len(rows)}.",
            data={"count": len(rows), "watches": rows},
        )

    async def remove_watch(self, watch_id: str) -> ToolResult:
        cursor = self.database.execute(
            "DELETE FROM website_watches WHERE watch_id = ?",
            (watch_id,),
        )
        self.database.commit()
        if cursor.rowcount == 0:
            return ToolResult.failure(
                "WEBSITE_WATCH_NOT_FOUND",
                f"Подписка '{watch_id}' не найдена.",
            )
        return ToolResult.ok(
            f"Подписка '{watch_id}' удалена.",
        )
