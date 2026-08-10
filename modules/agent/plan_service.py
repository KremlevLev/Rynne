# modules/agent/plan_service.py
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any
from collections.abc import Awaitable, Callable

from modules.agent.planning import (
    ExecutionPlan,
    PlanBudget,
    PlanExecutor,
    PlanStep,
    PlanStepStatus,
)
from modules.domain.results import ToolResult
from modules.tools.base import ToolContext
from modules.tools.runtime import (
    ToolRegistry,
    ToolRunner,
)


logger = logging.getLogger("PlanService")


class PlanService:
    """
    Фасад для создания и выполнения планов из tool call.

    LLM передаёт готовый структурированный план, а Nova:
    - валидирует шаги;
    - проверяет инструменты;
    - учитывает зависимости;
    - выполняет шаги;
    - проверяет результаты;
    - останавливается после критической ошибки.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        runner: ToolRunner,
        max_steps: int = 20,
        max_wall_time_seconds: float = 300.0,
    ) -> None:
        self.registry = registry
        self.runner = runner

        self.executor = PlanExecutor(
            registry=registry,
            runner=runner,
            budget=PlanBudget(
                max_steps=max_steps,
                max_wall_time_seconds=(
                    max_wall_time_seconds
                ),
            ),
        )

        self._active_cancellations: dict[
            str,
            asyncio.Event,
        ] = {}

        self._plans: dict[
            str,
            ExecutionPlan,
        ] = {}

        self._completed_plan_ids: set[str] = set()

    @staticmethod
    def _parse_steps(
        raw_steps: list[dict[str, Any]],
    ) -> list[PlanStep]:
        parsed_steps: list[PlanStep] = []

        for index, raw_step in enumerate(
            raw_steps,
            start=1,
        ):
            if not isinstance(raw_step, dict):
                continue

            step_id = str(
                raw_step.get("step_id")
                or f"step-{index}"
            ).strip()

            tool_name = str(
                raw_step.get("tool_name")
                or ""
            ).strip()

            raw_arguments = raw_step.get(
                "arguments",
                {},
            )

            arguments = (
                raw_arguments
                if isinstance(raw_arguments, dict)
                else {}
            )

            raw_dependencies = raw_step.get(
                "depends_on",
                [],
            )

            depends_on = (
                [
                    str(item)
                    for item in raw_dependencies
                ]
                if isinstance(
                    raw_dependencies,
                    list,
                )
                else []
            )

            parsed_step = PlanStep(
                step_id=step_id,
                tool_name=tool_name,
                arguments=arguments,
                depends_on=depends_on,
                description=str(
                    raw_step.get(
                        "description",
                        "",
                    )
                ),
                critical=bool(
                    raw_step.get(
                        "critical",
                        True,
                    )
                ),
            )
            if raw_step.get("status") == "completed":
                parsed_step.status = PlanStepStatus.COMPLETED
            parsed_steps.append(parsed_step)

        return parsed_steps

    async def execute_plan(
        self,
        goal: str,
        steps: list[dict[str, Any]],
        session_id: str = "plan-session",
        turn_id: str | None = None,
        *,
        plan_id: str | None = None,
        checkpoint_callback: Callable[
            [ExecutionPlan],
            Awaitable[None] | None,
        ]
        | None = None,
        context: ToolContext | None = None,
    ) -> ToolResult:
        if not goal.strip():
            return ToolResult.failure(
                "EMPTY_PLAN_GOAL",
                "Цель плана не указана.",
            )

        if not isinstance(steps, list):
            return ToolResult.failure(
                "INVALID_PLAN_STEPS",
                "Шаги плана должны быть массивом.",
            )

        parsed_steps = self._parse_steps(
            steps
        )

        resolved_turn_id = (
            turn_id
            or f"plan_turn_{uuid.uuid4().hex}"
        )

        plan = ExecutionPlan(
            goal=goal.strip(),
            steps=parsed_steps,
            **(
                {"plan_id": plan_id}
                if plan_id
                else {}
            ),
        )

        cancellation_event = asyncio.Event()

        self._plans[plan.plan_id] = plan
        self._active_cancellations[
            plan.plan_id
        ] = cancellation_event

        try:
            result = await self.executor.execute(
                plan,
                session_id=session_id,
                turn_id=resolved_turn_id,
                cancellation_event=(
                    cancellation_event
                ),
                checkpoint_callback=(
                    checkpoint_callback
                ),
                parent_context=context,
            )

            self._completed_plan_ids.add(plan.plan_id)
            return result.to_tool_result()

        finally:
            self._active_cancellations.pop(
                plan.plan_id,
                None,
            )

    def cancel_plan(
        self,
        plan_id: str,
    ) -> ToolResult:
        cancellation_event = (
            self._active_cancellations.get(
                plan_id
            )
        )

        if cancellation_event is None:
            return ToolResult.failure(
                "ACTIVE_PLAN_NOT_FOUND",
                (
                    f"Активный план '{plan_id}' "
                    "не найден."
                ),
            )

        cancellation_event.set()

        return ToolResult.ok(
            f"План '{plan_id}' отменяется.",
            data={
                "plan_id": plan_id,
            },
        )

    def get_plan_status(
        self,
        plan_id: str,
    ) -> ToolResult:
        plan = self._plans.get(plan_id)

        if plan is None:
            return ToolResult.failure(
                "PLAN_NOT_FOUND",
                f"План '{plan_id}' не найден.",
            )

        return ToolResult.ok(
            f"Статус плана '{plan_id}' получен.",
            data={
                "plan": plan.to_dict(),
                "active": (
                    plan_id
                    in self._active_cancellations
                ),
            },
        )

    def _get_completed_plan_ids(self) -> set[str]:
        """Возвращает множество ID завершённых планов."""
        return set(self._completed_plan_ids)
