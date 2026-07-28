from __future__ import annotations

import tempfile
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
