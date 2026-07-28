from __future__ import annotations

import asyncio
import json
from pathlib import Path

from modules.domain.ledger import (
    get_ledger,
    reset_ledger,
)
from modules.tools.base import ToolContext
from modules.tools.permissions import PermissionManager
from modules.tools.registry import ALL_TOOLS
from modules.tools.runtime import ToolRegistry, ToolRunner
from modules.windows import filesystem


class AllowingPermissionManager(PermissionManager):
    def check(self, policy_context):
        return True, None


def build_file_runner() -> ToolRunner:
    tool_names = {
        "write_text_file",
        "apply_text_patch",
        "undo_last_file_change",
    }
    schemas = [
        schema
        for schema in ALL_TOOLS
        if schema["function"]["name"] in tool_names
    ]
    registry = ToolRegistry.from_legacy(
        schemas,
        {
            "write_text_file": filesystem.write_text_file,
            "apply_text_patch": filesystem.apply_text_patch,
            "undo_last_file_change": (
                filesystem.undo_last_file_change
            ),
        },
    )
    return ToolRunner(
        registry,
        permission_manager=AllowingPermissionManager(),
    )


async def execute(
    runner: ToolRunner,
    tool_name: str,
    arguments: dict,
):
    return await runner.execute(
        {
            "id": f"call_{tool_name}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(arguments),
            },
        },
        context=ToolContext.create(
            session_id="safe-undo-test",
            turn_id=f"turn-{tool_name}",
        ),
    )


def test_undo_restores_exact_previous_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reset_ledger()
    monkeypatch.setattr(
        filesystem,
        "BACKUP_DIR",
        tmp_path / "backups",
    )
    path = tmp_path / "app.py"
    path.write_text("version = 1\n", encoding="utf-8")
    runner = build_file_runner()

    write_result = asyncio.run(
        execute(
            runner,
            "write_text_file",
            {
                "path": str(path),
                "content": "version = 2\n",
            },
        )
    )
    undo_result = asyncio.run(
        execute(
            runner,
            "undo_last_file_change",
            {},
        )
    )

    assert write_result.success
    assert undo_result.success
    assert path.read_text(encoding="utf-8") == "version = 1\n"
    reversible = get_ledger().get_rollbackable_records()
    assert len(reversible) == 1
    assert reversible[0].rollback_info["undone"] is True
    assert (
        undo_result.verification.method
        == "backup_restore_sha256"
    )


def test_undo_refuses_to_overwrite_newer_manual_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reset_ledger()
    monkeypatch.setattr(
        filesystem,
        "BACKUP_DIR",
        tmp_path / "backups",
    )
    path = tmp_path / "settings.py"
    path.write_text("mode = 'old'\n", encoding="utf-8")
    runner = build_file_runner()

    asyncio.run(
        execute(
            runner,
            "apply_text_patch",
            {
                "path": str(path),
                "patch": "= mode = 'old' -> mode = 'nova'",
            },
        )
    )
    path.write_text(
        "mode = 'manual'\n",
        encoding="utf-8",
    )
    undo_result = asyncio.run(
        execute(
            runner,
            "undo_last_file_change",
            {},
        )
    )

    assert not undo_result.success
    assert undo_result.code == "ROLLBACK_CONFLICT"
    assert (
        path.read_text(encoding="utf-8")
        == "mode = 'manual'\n"
    )


def test_multiple_undos_walk_back_change_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reset_ledger()
    monkeypatch.setattr(
        filesystem,
        "BACKUP_DIR",
        tmp_path / "backups",
    )
    path = tmp_path / "counter.txt"
    path.write_text("one", encoding="utf-8")
    runner = build_file_runner()

    for content in ("two", "three"):
        result = asyncio.run(
            execute(
                runner,
                "write_text_file",
                {
                    "path": str(path),
                    "content": content,
                },
            )
        )
        assert result.success

    first_undo = asyncio.run(
        execute(runner, "undo_last_file_change", {})
    )
    assert first_undo.success
    assert path.read_text(encoding="utf-8") == "two"

    second_undo = asyncio.run(
        execute(runner, "undo_last_file_change", {})
    )
    assert second_undo.success
    assert path.read_text(encoding="utf-8") == "one"

