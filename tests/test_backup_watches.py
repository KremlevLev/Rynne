from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from modules.agent.backup_watches import BackupWatchManager
from modules.agent.proactive import ProactiveSuggestionEngine
from modules.storage.database import Database


def test_stale_backup_alerts_again_only_after_recovery() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "nova.db")
            backup = root / "project.backup"
            backup.write_text("opaque backup", encoding="utf-8")
            now = 100_000.0
            os.utime(backup, (now - 7200, now - 7200))

            manager = BackupWatchManager(
                database,
                clock=lambda: now,
            )
            added = manager.add_watch(
                str(backup),
                max_age_hours=1,
                label="Project",
            )
            assert added.success

            engine = ProactiveSuggestionEngine(
                database,
                cooldown_seconds=0,
                clock=lambda: now,
                local_hour=lambda: 12,
            )
            stale = await manager.poll()
            first = engine.observe_backup_statuses(stale)
            repeated = engine.observe_backup_statuses(stale)

            assert len(first) == 1
            assert first[0].kind == "backup_stale"
            assert repeated == []
            assert "opaque backup" not in first[0].message

            os.utime(backup, (now, now))
            healthy = await manager.poll()
            assert engine.observe_backup_statuses(healthy) == []

            os.utime(backup, (now - 7200, now - 7200))
            stale_again = await manager.poll()
            second = engine.observe_backup_statuses(stale_again)

            assert len(second) == 1
            assert second[0].source_key != first[0].source_key
            database.close()

    asyncio.run(scenario())


def test_missing_backup_creates_high_priority_alert() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "nova.db")
            backup = root / "daily.zip"
            backup.write_bytes(b"backup")
            manager = BackupWatchManager(database)
            added = manager.add_watch(str(backup))
            assert added.success

            backup.unlink()
            statuses = await manager.poll()
            engine = ProactiveSuggestionEngine(
                database,
                cooldown_seconds=0,
                local_hour=lambda: 12,
            )
            suggestions = engine.observe_backup_statuses(statuses)

            assert len(suggestions) == 1
            assert suggestions[0].kind == "backup_missing"
            assert suggestions[0].importance == "high"
            database.close()

    asyncio.run(scenario())


def test_backup_watch_can_be_listed_and_removed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = Database(root / "nova.db")
        backup_directory = root / "backups"
        backup_directory.mkdir()
        manager = BackupWatchManager(database)

        added = manager.add_watch(
            str(backup_directory),
            max_age_hours=48,
            label="Daily",
        )
        duplicate = manager.add_watch(str(backup_directory))
        listed = manager.list_watches()
        removed = manager.remove_watch(
            str(added.data["watch_id"])
        )

        assert added.success
        assert duplicate.success
        assert duplicate.data["watch_id"] == added.data["watch_id"]
        assert listed.data["count"] == 1
        assert listed.data["watches"][0]["max_age_hours"] == 48
        assert removed.success
        assert manager.list_watches().data["count"] == 0
        database.close()
