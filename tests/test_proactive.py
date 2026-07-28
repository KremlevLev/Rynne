from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.agent.background_plans import (
    BackgroundPlan,
    BackgroundPlanStatus,
)
from modules.agent.proactive import ProactiveSuggestionEngine
from modules.storage.database import Database


def make_plan(
    background_id: str,
    status: BackgroundPlanStatus,
) -> BackgroundPlan:
    return BackgroundPlan(
        background_id=background_id,
        goal=f"goal {background_id}",
        steps=[],
        session_id="session",
        turn_id="turn",
        plan_id=f"plan_{background_id}",
        status=status,
    )


def test_completed_background_plan_is_suggested_only_once() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            local_hour=lambda: 12,
        )
        plan = make_plan(
            "one",
            BackgroundPlanStatus.COMPLETED,
        )

        first = engine.observe_background_plans([plan])
        second = engine.observe_background_plans([plan])

        assert len(first) == 1
        assert first[0].kind == "background_plan_completed"
        assert "completed" in first[0].reason
        assert second == []
        assert len(engine.journal()) == 1
        database.close()


def test_failed_plan_suggests_resume_after_delay() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        now = [100.0]
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            clock=lambda: now[0],
            local_hour=lambda: 12,
        )
        plan = make_plan(
            "resume",
            BackgroundPlanStatus.FAILED,
        )
        plan.finished_at = now[0]
        plan.attempts = 1

        assert engine.observe_incomplete_plans(
            [plan],
            suggest_after_seconds=60,
        ) == []
        now[0] += 61
        first = engine.observe_incomplete_plans(
            [plan],
            suggest_after_seconds=60,
        )
        repeated = engine.observe_incomplete_plans(
            [plan],
            suggest_after_seconds=60,
        )

        assert len(first) == 1
        assert first[0].kind == "background_plan_resume_suggested"
        assert "checkpoint" in first[0].message
        assert repeated == []
        database.close()


def test_proactive_cooldown_delays_similar_suggestion() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        now = [100.0]
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=60,
            clock=lambda: now[0],
            local_hour=lambda: 12,
        )
        plans = [
            make_plan("one", BackgroundPlanStatus.FAILED),
            make_plan("two", BackgroundPlanStatus.FAILED),
        ]

        assert len(engine.observe_background_plans(plans)) == 1
        now[0] += 61
        later = engine.observe_background_plans(plans)

        assert len(later) == 1
        assert later[0].source_key.endswith("two:failed")
        database.close()


def test_proactive_suggestions_respect_quiet_hours() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            quiet_hours=(22, 8),
            local_hour=lambda: 23,
        )

        suggestions = engine.observe_background_plans(
            [
                make_plan(
                    "quiet",
                    BackgroundPlanStatus.COMPLETED,
                )
            ]
        )

        assert suggestions == []
        assert engine.journal() == []
        database.close()


def test_failed_server_process_creates_high_priority_suggestion() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            local_hour=lambda: 12,
        )
        process = {
            "process_id": "proc_server",
            "label": "development server",
            "command": ["python", "-m", "http.server"],
            "status": "exited",
            "exit_code": 1,
            "health_check_port": 8000,
        }

        suggestions = engine.observe_processes([process])

        assert len(suggestions) == 1
        assert suggestions[0].kind == "server_stopped"
        assert suggestions[0].importance == "high"
        assert "running → exited" in suggestions[0].reason
        assert engine.observe_processes([process]) == []
        database.close()


def test_successful_test_process_is_classified_separately() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            local_hour=lambda: 12,
        )

        suggestions = engine.observe_processes(
            [
                {
                    "process_id": "proc_tests",
                    "label": "pytest",
                    "command": ["python", "-m", "pytest"],
                    "status": "exited",
                    "exit_code": 0,
                }
            ]
        )

        assert len(suggestions) == 1
        assert suggestions[0].kind == "tests_completed"
        database.close()


def test_disk_space_alerts_only_on_new_low_space_transition() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            local_hour=lambda: 12,
        )
        gib = 1024**3
        low_usage = (100 * gib, 95 * gib, 5 * gib)
        normal_usage = (100 * gib, 60 * gib, 40 * gib)

        first = engine.observe_disk_space(
            directory,
            free_percent_threshold=10,
            free_bytes_threshold=0,
            usage=low_usage,
        )
        repeated = engine.observe_disk_space(
            directory,
            free_percent_threshold=10,
            free_bytes_threshold=0,
            usage=low_usage,
        )
        recovered = engine.observe_disk_space(
            directory,
            free_percent_threshold=10,
            free_bytes_threshold=0,
            usage=normal_usage,
        )
        second = engine.observe_disk_space(
            directory,
            free_percent_threshold=10,
            free_bytes_threshold=0,
            usage=low_usage,
        )

        assert len(first) == 1
        assert first[0].kind == "disk_space_low"
        assert repeated == []
        assert recovered == []
        assert len(second) == 1
        assert second[0].source_key != first[0].source_key
        assert len(engine.journal()) == 2
        database.close()


def test_disk_space_state_survives_engine_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        usage = (1000, 950, 50)
        first_engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            local_hour=lambda: 12,
        )

        assert len(
            first_engine.observe_disk_space(
                directory,
                free_percent_threshold=10,
                free_bytes_threshold=0,
                usage=usage,
            )
        ) == 1

        restarted_engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            local_hour=lambda: 12,
        )
        assert restarted_engine.observe_disk_space(
            directory,
            free_percent_threshold=10,
            free_bytes_threshold=0,
            usage=usage,
        ) == []
        database.close()


def test_proactive_kind_can_be_disabled() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            disabled_kinds={"disk_space_low"},
            local_hour=lambda: 12,
        )

        suggestions = engine.observe_disk_space(
            directory,
            free_percent_threshold=10,
            free_bytes_threshold=0,
            usage=(1000, 950, 50),
        )

        assert suggestions == []
        assert engine.journal() == []
        database.close()


def test_stale_process_suggests_cleanup_only_once() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        now = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            clock=lambda: now.timestamp(),
            local_hour=lambda: 12,
        )
        process = {
            "process_id": "proc_worker",
            "label": "one-off report",
            "command": ["python", "report.py"],
            "status": "running",
            "started_at": (
                now - timedelta(hours=5)
            ).isoformat(),
        }

        first = engine.observe_stale_processes(
            [process],
            stale_after_seconds=4 * 60 * 60,
        )
        repeated = engine.observe_stale_processes(
            [process],
            stale_after_seconds=4 * 60 * 60,
        )

        assert len(first) == 1
        assert first[0].kind == "stale_process"
        assert "5.0 ч" in first[0].message
        assert repeated == []
        database.close()


def test_stale_process_monitor_ignores_servers() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        now = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            clock=lambda: now.timestamp(),
            local_hour=lambda: 12,
        )

        suggestions = engine.observe_stale_processes(
            [
                {
                    "process_id": "proc_server",
                    "label": "development server",
                    "command": ["python", "-m", "http.server"],
                    "status": "running",
                    "started_at": (
                        now - timedelta(days=1)
                    ).isoformat(),
                    "health_check_port": 8000,
                }
            ],
            stale_after_seconds=60,
        )

        assert suggestions == []
        database.close()


def test_repository_suggests_commit_once_per_dirty_cycle() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        now = [100.0]
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            clock=lambda: now[0],
            local_hour=lambda: 12,
        )
        status = " M modules/agent.py\n?? notes.txt"

        assert engine.observe_repository(
            directory,
            status,
            uncommitted_after_seconds=60,
        ) == []
        now[0] += 61
        first = engine.observe_repository(
            directory,
            status,
            uncommitted_after_seconds=60,
        )
        repeated = engine.observe_repository(
            directory,
            status,
            uncommitted_after_seconds=60,
        )

        assert len(first) == 1
        assert first[0].kind == "repository_uncommitted"
        assert "2 изменённых" in first[0].message
        assert repeated == []

        assert engine.observe_repository(directory, "") == []
        second = engine.observe_repository(
            directory,
            " M README.md",
            uncommitted_after_seconds=0,
        )

        assert len(second) == 1
        assert second[0].source_key != first[0].source_key
        database.close()


def test_repository_conflict_is_reported_immediately() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            clock=lambda: 100.0,
            local_hour=lambda: 12,
        )

        first = engine.observe_repository(
            directory,
            "UU modules/agent.py\n M README.md",
        )
        repeated = engine.observe_repository(
            directory,
            "UU modules/agent.py\n M README.md",
        )

        assert len(first) == 1
        assert first[0].kind == "repository_conflict"
        assert first[0].importance == "high"
        assert repeated == []
        database.close()


def test_tool_activity_stores_only_successful_non_read_only_metadata() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            clock=lambda: 100.0,
            local_hour=lambda: 12,
        )
        base = {
            "session_id": "session",
            "turn_id": "turn",
            "tool_name": "write_text_file",
            "risk": "write",
            "success": True,
            "arguments": {"content": "secret"},
            "message": "private result",
        }

        engine.record_tool_completion(
            {**base, "operation_id": "successful"}
        )
        engine.record_tool_completion(
            {
                **base,
                "operation_id": "failed",
                "success": False,
            }
        )
        engine.record_tool_completion(
            {
                **base,
                "operation_id": "read",
                "tool_name": "read_text_file",
                "risk": "read_only",
            }
        )

        rows = database.fetchall(
            "SELECT * FROM tool_activity"
        )
        assert len(rows) == 1
        assert rows[0] == {
            "operation_id": "successful",
            "tool_name": "write_text_file",
            "session_id": "session",
            "turn_id": "turn",
            "observed_at": 100.0,
        }
        database.close()


def test_repeated_tool_sequence_suggests_workflow_once() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        now = [100.0]
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            clock=lambda: now[0],
            local_hour=lambda: 12,
        )
        for turn_index in range(3):
            for tool_index, tool_name in enumerate(
                ("open_application", "write_in_application")
            ):
                now[0] += 1
                engine.record_tool_completion(
                    {
                        "operation_id": (
                            f"op_{turn_index}_{tool_index}"
                        ),
                        "session_id": "session",
                        "turn_id": f"turn_{turn_index}",
                        "tool_name": tool_name,
                        "risk": "write",
                        "success": True,
                    }
                )

        first = engine.observe_repeated_actions(
            min_repetitions=3,
            lookback_seconds=1000,
        )
        repeated = engine.observe_repeated_actions(
            min_repetitions=3,
            lookback_seconds=1000,
        )

        assert len(first) == 1
        assert first[0].kind == "workflow_suggested"
        assert "open_application → write_in_application" in (
            first[0].message
        )
        assert repeated == []
        database.close()


def test_workflow_is_not_suggested_before_repetition_threshold() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "nova.db")
        now = [100.0]
        engine = ProactiveSuggestionEngine(
            database,
            cooldown_seconds=0,
            clock=lambda: now[0],
            local_hour=lambda: 12,
        )
        for index in range(2):
            engine.record_tool_completion(
                {
                    "operation_id": f"op_{index}",
                    "session_id": "session",
                    "turn_id": f"turn_{index}",
                    "tool_name": "open_application",
                    "risk": "low",
                    "success": True,
                }
            )

        assert engine.observe_repeated_actions(
            min_repetitions=3,
            lookback_seconds=1000,
        ) == []

        now[0] = 1000.0
        assert engine.observe_repeated_actions(
            min_repetitions=3,
            lookback_seconds=100,
        ) == []
        assert database.fetchall(
            "SELECT operation_id FROM tool_activity"
        ) == []
        database.close()
