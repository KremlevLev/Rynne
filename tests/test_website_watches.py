from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from modules.agent.proactive import ProactiveSuggestionEngine
from modules.agent.website_watches import (
    WebsiteWatchManager,
    validate_public_url,
)
from modules.storage.database import Database


async def allow_url(
    url: str,
) -> tuple[bool, str | None, str | None]:
    return True, url, None


def test_local_website_watch_is_blocked() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "nova.db")
            manager = WebsiteWatchManager(database)

            result = await manager.add_watch(
                "http://localhost:8000/private"
            )

            assert not result.success
            assert result.code == "WEBSITE_URL_BLOCKED"
            database.close()

    asyncio.run(scenario())


def test_website_change_creates_one_pending_notification() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "nova.db")
            content = ["initial private text"]

            async def fetch(_url: str) -> str:
                return content[0]

            manager = WebsiteWatchManager(
                database,
                fetcher=fetch,
                validator=allow_url,
                clock=lambda: 100.0,
            )
            added = await manager.add_watch(
                "https://example.com/page",
                "Release page",
            )
            assert added.success

            content[0] = "changed private text"
            changes = await manager.poll()
            assert len(changes) == 1
            assert changes[0]["revision"] == 1

            engine = ProactiveSuggestionEngine(
                database,
                cooldown_seconds=0,
                clock=lambda: 100.0,
                local_hour=lambda: 12,
            )
            suggestions = engine.observe_website_changes(changes)
            assert len(suggestions) == 1
            assert suggestions[0].kind == "website_changed"
            assert "private text" not in suggestions[0].message

            manager.mark_notified(
                str(changes[0]["watch_id"]),
                int(changes[0]["revision"]),
            )
            assert manager.pending_changes() == []
            assert await manager.poll() == []

            row = database.fetchone(
                """
                SELECT content_hash, last_error
                FROM website_watches
                WHERE watch_id = ?
                """,
                (added.data["watch_id"],),
            )
            assert row is not None
            assert "private text" not in row["content_hash"]
            assert row["last_error"] is None
            database.close()

    asyncio.run(scenario())


def test_website_watch_can_be_listed_and_removed() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "nova.db")

            async def fetch(_url: str) -> str:
                return "baseline"

            manager = WebsiteWatchManager(
                database,
                fetcher=fetch,
                validator=allow_url,
            )
            added = await manager.add_watch(
                "https://example.com",
                "Example",
            )

            duplicate = await manager.add_watch(
                "https://example.com",
            )
            listed = await manager.list_watches()
            removed = await manager.remove_watch(
                str(added.data["watch_id"])
            )
            listed_after = await manager.list_watches()

            assert duplicate.success
            assert duplicate.data["watch_id"] == added.data["watch_id"]
            assert listed.data["count"] == 1
            assert removed.success
            assert listed_after.data["count"] == 0
            database.close()

    asyncio.run(scenario())


def test_public_url_validator_rejects_private_ip() -> None:
    async def scenario() -> None:
        valid, normalized, error = await validate_public_url(
            "http://127.0.0.1/admin"
        )

        assert valid is False
        assert normalized is None
        assert error is not None

    asyncio.run(scenario())
