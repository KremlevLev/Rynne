# tests/test_background_plans.py
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from modules.agent.background_plans import (
    BackgroundPlanManager,
    BackgroundPlanStatus,
)
from modules.domain.results import ToolResult
from modules.domain.results import VerificationResult
from modules.agent.plan_service import PlanService
from modules.storage.database import Database
from modules.tools.base import (
    RiskLevel,
    ToolCategory,
    ToolDefinition,
)
from modules.tools.runtime import ToolRegistry, ToolRunner


class FakePlanService:
    async def execute_plan(
        self,
        goal,
        steps,
        session_id,
        turn_id,
    ):
        await asyncio.sleep(0.01)

        return ToolResult.ok(
            "План выполнен.",
            data={
                "goal": goal,
            },
        )


class SlowPlanService:
    async def execute_plan(
        self,
        goal,
        steps,
        session_id,
        turn_id,
    ):
        await asyncio.sleep(10)

        return ToolResult.ok("Готово.")


class FlakyPlanService:
    def __init__(self) -> None:
        self.calls = 0
        self.received_steps: list[list[dict]] = []

    async def execute_plan(
        self,
        goal,
        steps,
        session_id,
        turn_id,
    ):
        self.calls += 1
        self.received_steps.append(
            [dict(step) for step in steps]
        )
        if self.calls == 1:
            steps[0]["status"] = "completed"
            return ToolResult.failure(
                "TEMPORARY_FAILURE",
                "Временная ошибка.",
            )
        return ToolResult.ok("План продолжен.")


def test_background_plan_completes() -> None:
    async def scenario() -> None:
        manager = BackgroundPlanManager(
            FakePlanService()
        )

        start_result = await manager.start_plan(
            goal="Тест",
            steps=[
                {
                    "step_id": "one",
                    "tool_name": "echo",
                    "arguments": {},
                }
            ],
        )

        assert start_result.success

        background_id = (
            start_result.data["background_id"]
        )

        await asyncio.sleep(0.05)

        status_result = await manager.get_status(
            background_id
        )

        assert status_result.success
        assert (
            status_result.data["status"]
            == BackgroundPlanStatus.COMPLETED.value
        )

        await manager.close()

    asyncio.run(scenario())


def test_failed_background_plan_can_resume_from_checkpoint() -> None:
    async def scenario() -> None:
        service = FlakyPlanService()
        manager = BackgroundPlanManager(service)
        started = await manager.start_plan(
            goal="Продолжить отчёт",
            steps=[
                {
                    "step_id": "one",
                    "tool_name": "prepare",
                    "arguments": {},
                },
                {
                    "step_id": "two",
                    "tool_name": "publish",
                    "arguments": {},
                },
            ],
        )
        background_id = started.data["background_id"]
        await asyncio.sleep(0.05)

        failed = await manager.get_status(background_id)
        assert failed.data["status"] == "failed"
        assert failed.data["attempts"] == 1

        retried = await manager.retry_plan(background_id)
        assert retried.success
        await asyncio.sleep(0.05)

        completed = await manager.get_status(background_id)
        assert completed.data["status"] == "completed"
        assert completed.data["attempts"] == 2
        assert (
            service.received_steps[1][0]["status"]
            == "completed"
        )
        await manager.close()

    asyncio.run(scenario())


def test_background_plan_can_be_cancelled() -> None:
    async def scenario() -> None:
        manager = BackgroundPlanManager(
            SlowPlanService()
        )

        start_result = await manager.start_plan(
            goal="Долгий тест",
            steps=[
                {
                    "step_id": "one",
                    "tool_name": "echo",
                    "arguments": {},
                }
            ],
        )

        background_id = (
            start_result.data["background_id"]
        )

        cancel_result = await manager.cancel_plan(
            background_id
        )

        assert cancel_result.success

        status_result = await manager.get_status(
            background_id
        )

        assert (
            status_result.data["status"]
            == BackgroundPlanStatus.CANCELLED.value
        )

        await manager.close()

    asyncio.run(scenario())


def test_unknown_background_plan() -> None:
    async def scenario() -> None:
        manager = BackgroundPlanManager(
            FakePlanService()
        )

        result = await manager.get_status(
            "missing"
        )

        assert not result.success
        assert (
            result.code
            == "BACKGROUND_PLAN_NOT_FOUND"
        )

        await manager.close()

    asyncio.run(scenario())


def test_list_background_plans() -> None:
    async def scenario() -> None:
        manager = BackgroundPlanManager(
            FakePlanService()
        )

        await manager.start_plan(
            goal="Первый",
            steps=[
                {
                    "step_id": "one",
                    "tool_name": "echo",
                    "arguments": {},
                }
            ],
        )

        result = await manager.list_plans()

        assert result.success
        assert result.data["count"] == 1

        await manager.close()

    asyncio.run(scenario())


def test_background_plan_resumes_from_durable_checkpoint() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "nova.db")
            calls = {"first": 0, "second": 0}

            async def first() -> ToolResult:
                calls["first"] += 1
                return ToolResult.ok(
                    "first",
                    verification=VerificationResult(
                        verified=True,
                        method="test",
                        confidence=1.0,
                    ),
                )

            async def slow_second() -> ToolResult:
                calls["second"] += 1
                await asyncio.sleep(10)
                return ToolResult.ok("second")

            def make_service(second_handler) -> PlanService:
                registry = ToolRegistry()
                for name, handler in (
                    ("first", first),
                    ("second", second_handler),
                ):
                    registry.register_definition(
                        ToolDefinition(
                            name=name,
                            description=name,
                            parameters={
                                "type": "object",
                                "properties": {},
                            },
                            handler=handler,
                            category=ToolCategory.SYSTEM_READ,
                            risk=RiskLevel.READ_ONLY,
                        )
                    )
                return PlanService(
                    registry=registry,
                    runner=ToolRunner(registry),
                )

            manager = BackgroundPlanManager(
                make_service(slow_second),
                database,
            )
            started = await manager.start_plan(
                goal="resume",
                steps=[
                    {
                        "step_id": "first",
                        "tool_name": "first",
                        "arguments": {},
                    },
                    {
                        "step_id": "second",
                        "tool_name": "second",
                        "arguments": {},
                        "depends_on": ["first"],
                    },
                ],
            )
            background_id = started.data["background_id"]

            for _ in range(100):
                row = database.fetchone(
                    """
                    SELECT payload FROM background_plans
                    WHERE background_id = ?
                    """,
                    (background_id,),
                )
                payload = json.loads(row["payload"])
                if payload["steps"][0].get("status") == "completed":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("checkpoint was not persisted")

            await manager.close()
            assert calls["first"] == 1

            async def fast_second() -> ToolResult:
                calls["second"] += 1
                return ToolResult.ok(
                    "second",
                    verification=VerificationResult(
                        verified=True,
                        method="test",
                        confidence=1.0,
                    ),
                )

            restored = BackgroundPlanManager(
                make_service(fast_second),
                database,
            )
            for _ in range(100):
                status = await restored.get_status(background_id)
                if (
                    status.data["status"]
                    == BackgroundPlanStatus.COMPLETED.value
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("plan was not resumed")

            assert calls["first"] == 1
            # The interrupted second step may have begun before shutdown, but
            # the completed first side effect is never repeated.
            assert calls["second"] >= 1
            assert status.data["recovered"] is True

            await restored.close()
            database.close()

    asyncio.run(scenario())


def test_persisted_user_cancellation_is_not_resumed() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "nova.db")
            payload = {
                "background_id": "background_cancelled",
                "goal": "do not resume",
                "steps": [
                    {
                        "step_id": "one",
                        "tool_name": "echo",
                        "arguments": {},
                    }
                ],
                "session_id": "session",
                "turn_id": "turn",
                "plan_id": "plan_cancelled",
                "status": "cancelling",
                "created_at": 1.0,
            }
            database.execute(
                """
                INSERT INTO background_plans (
                    background_id, payload
                ) VALUES (?, ?)
                """,
                (
                    payload["background_id"],
                    json.dumps(payload),
                ),
            )
            database.commit()

            manager = BackgroundPlanManager(
                FakePlanService(),
                database,
            )
            await asyncio.sleep(0.02)
            status = await manager.get_status(
                payload["background_id"]
            )

            assert (
                status.data["status"]
                == BackgroundPlanStatus.CANCELLED.value
            )
            assert status.data["result"] is None

            await manager.close()
            database.close()

    asyncio.run(scenario())
