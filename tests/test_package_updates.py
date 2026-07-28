from __future__ import annotations

import asyncio
import importlib.metadata
import tempfile
from pathlib import Path

from modules.agent.package_updates import PackageUpdateManager
from modules.agent.proactive import ProactiveSuggestionEngine
from modules.storage.database import Database


def test_package_update_notifies_once_per_new_version() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "nova.db")
            installed = ["1.9"]
            latest = ["1.10"]

            async def fetch(_package: str) -> str:
                return latest[0]

            manager = PackageUpdateManager(
                database,
                fetcher=fetch,
                version_getter=lambda _package: installed[0],
                clock=lambda: 100.0,
            )
            added = await manager.add_watch("Requests")
            assert added.success
            assert added.data["package_name"] == "requests"
            assert added.data["update_available"] is True

            statuses = await manager.poll()
            engine = ProactiveSuggestionEngine(
                database,
                cooldown_seconds=0,
                clock=lambda: 100.0,
                local_hour=lambda: 12,
            )
            first = engine.observe_package_updates(statuses)
            repeated = engine.observe_package_updates(statuses)

            assert len(first) == 1
            assert first[0].kind == "package_update_available"
            assert "1.9 → 1.10" in first[0].message
            assert repeated == []

            installed[0] = "1.10"
            assert engine.observe_package_updates(
                await manager.poll()
            ) == []

            latest[0] = "2.0"
            second = engine.observe_package_updates(
                await manager.poll()
            )
            assert len(second) == 1
            assert second[0].source_key != first[0].source_key
            database.close()

    asyncio.run(scenario())


def test_package_watch_rejects_invalid_or_missing_package() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "nova.db")

            def missing(_package: str) -> str:
                raise importlib.metadata.PackageNotFoundError

            async def fetch(_package: str) -> str:
                return "1.0"

            manager = PackageUpdateManager(
                database,
                fetcher=fetch,
                version_getter=missing,
            )

            invalid = await manager.add_watch(
                "requests/../../private"
            )
            not_installed = await manager.add_watch(
                "missing-package"
            )

            assert invalid.code == "INVALID_PACKAGE"
            assert not_installed.code == "PACKAGE_NOT_INSTALLED"
            assert manager.list_watches().data["count"] == 0
            database.close()

    asyncio.run(scenario())


def test_package_watch_can_be_listed_and_removed() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "nova.db")

            async def fetch(_package: str) -> str:
                return "2.0"

            manager = PackageUpdateManager(
                database,
                fetcher=fetch,
                version_getter=lambda _package: "1.0",
            )
            added = await manager.add_watch("demo_package")
            duplicate = await manager.add_watch("demo-package")
            listed = manager.list_watches()
            removed = manager.remove_watch(
                str(added.data["watch_id"])
            )

            assert added.success
            assert duplicate.success
            assert duplicate.data["watch_id"] == added.data["watch_id"]
            assert listed.data["count"] == 1
            assert removed.success
            assert manager.list_watches().data["count"] == 0
            database.close()

    asyncio.run(scenario())
