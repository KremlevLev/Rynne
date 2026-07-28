# modules/agent/planning.py
from __future__ import annotations
from modules.agent.recovery import (
    RecoveryEngine,
)
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from collections.abc import Awaitable, Callable
from typing import Any

from modules.domain.results import (
    ToolResult,
    VerificationResult,
)
from modules.tools.base import ToolContext
from modules.tools.runtime import (
    ToolRegistry,
    ToolRunner,
)


logger = logging.getLogger("PlanExecutor")


class PlanStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class PlanStep:
    step_id: str
    tool_name: str
    arguments: dict[str, Any]

    depends_on: list[str] = field(
        default_factory=list
    )

    description: str = ""
    critical: bool = True

    status: PlanStepStatus = (
        PlanStepStatus.PENDING
    )

    result: ToolResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "depends_on": self.depends_on,
            "description": self.description,
            "critical": self.critical,
            "status": self.status.value,
            "result": (
                self.result.to_dict()
                if self.result is not None
                else None
            ),
        }


@dataclass(slots=True)
class ExecutionPlan:
    goal: str
    steps: list[PlanStep]

    plan_id: str = field(
        default_factory=lambda: (
            f"plan_{uuid.uuid4().hex}"
        )
    )

    created_at: float = field(
        default_factory=time.time
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "created_at": self.created_at,
            "steps": [
                step.to_dict()
                for step in self.steps
            ],
        }


@dataclass(slots=True)
class PlanBudget:
    max_steps: int = 20
    max_wall_time_seconds: float = 300.0


@dataclass(slots=True)
class PlanValidationResult:
    valid: bool
    errors: list[str] = field(
        default_factory=list
    )


@dataclass(slots=True)
class PlanExecutionResult:
    success: bool
    plan: ExecutionPlan

    completed_steps: int
    failed_steps: int
    skipped_steps: int

    error_code: str | None = None
    message: str = ""

    def to_tool_result(self) -> ToolResult:
        return ToolResult(
            success=self.success,
            code=self.error_code or "OK",
            message=self.message,
            data={
                "plan": self.plan.to_dict(),
                "completed_steps": (
                    self.completed_steps
                ),
                "failed_steps": self.failed_steps,
                "skipped_steps": self.skipped_steps,
            },
            verification=VerificationResult(
                verified=self.success,
                method="plan_step_results",
                confidence=1.0,
                details=self.message,
            ),
        )


class PlanValidator:
    @staticmethod
    def validate(
        plan: ExecutionPlan,
        registry: ToolRegistry,
        *,
        max_steps: int = 20,
    ) -> PlanValidationResult:
        errors: list[str] = []

        if not plan.goal.strip():
            errors.append(
                "Цель плана не указана."
            )

        if not plan.steps:
            errors.append(
                "План не содержит шагов."
            )

        if len(plan.steps) > max_steps:
            errors.append(
                (
                    f"План содержит {len(plan.steps)} "
                    f"шагов при лимите {max_steps}."
                )
            )

        step_ids = [
            step.step_id
            for step in plan.steps
        ]

        if len(step_ids) != len(set(step_ids)):
            errors.append(
                "Идентификаторы шагов должны быть уникальными."
            )

        known_step_ids = set(step_ids)

        for step in plan.steps:
            if not step.step_id.strip():
                errors.append(
                    "Найден шаг без идентификатора."
                )

            if registry.get(
                step.tool_name
            ) is None:
                errors.append(
                    (
                        f"Инструмент '{step.tool_name}' "
                        f"шага '{step.step_id}' "
                        "не зарегистрирован."
                    )
                )
            if step.tool_name in {
                "execute_plan",
                "cancel_plan",
                "get_plan_status",
            }:
                errors.append(
                    (
                        f"Планировочный инструмент "
                        f"'{step.tool_name}' запрещён "
                        "внутри плана."
                    )
                )

            for dependency in step.depends_on:
                if dependency not in known_step_ids:
                    errors.append(
                        (
                            f"Шаг '{step.step_id}' зависит "
                            f"от неизвестного шага "
                            f"'{dependency}'."
                        )
                    )

                if dependency == step.step_id:
                    errors.append(
                        (
                            f"Шаг '{step.step_id}' "
                            "не может зависеть от себя."
                        )
                    )

        if PlanValidator._has_cycle(
            plan.steps
        ):
            errors.append(
                "План содержит циклические зависимости."
            )

        return PlanValidationResult(
            valid=not errors,
            errors=errors,
        )

    @staticmethod
    def _has_cycle(
        steps: list[PlanStep],
    ) -> bool:
        graph = {
            step.step_id: set(step.depends_on)
            for step in steps
        }

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> bool:
            if step_id in visiting:
                return True

            if step_id in visited:
                return False

            visiting.add(step_id)

            for dependency in graph.get(
                step_id,
                set(),
            ):
                if visit(dependency):
                    return True

            visiting.remove(step_id)
            visited.add(step_id)
            return False

        return any(
            visit(step_id)
            for step_id in graph
        )


class StepVerifier:
    @staticmethod
    def verify(
        step: PlanStep,
        result: ToolResult,
    ) -> tuple[bool, str]:
        if not result.success:
            return (
                False,
                result.message,
            )

        if result.verification.verified is False:
            return (
                False,
                (
                    "Инструмент сообщил об успехе, "
                    "но проверка результата не пройдена: "
                    f"{result.verification.details}"
                ),
            )

        return True, result.message


class PlanExecutor:
    """
    Выполняет валидированный план по зависимостям.

    Пока шаги выполняются последовательно. Параллельное выполнение
    read-only шагов можно добавить после появления lock manager.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        runner: ToolRunner,
        budget: PlanBudget | None = None,
    ) -> None:
        self.registry = registry
        self.runner = runner
        self.budget = budget or PlanBudget()
        self.recovery_engine = RecoveryEngine()

    @staticmethod
    def _build_tool_call(
        step: PlanStep,
    ) -> dict[str, Any]:
        import json

        return {
            "id": (
                f"plan_call_{uuid.uuid4().hex}"
            ),
            "type": "function",
            "function": {
                "name": step.tool_name,
                "arguments": json.dumps(
                    step.arguments,
                    ensure_ascii=False,
                ),
            },
        }

    @staticmethod
    def _dependencies_completed(
        step: PlanStep,
        steps_by_id: dict[str, PlanStep],
    ) -> bool:
        return all(
            steps_by_id[dependency].status
            == PlanStepStatus.COMPLETED
            for dependency in step.depends_on
        )

    @staticmethod
    def _dependency_failed(
        step: PlanStep,
        steps_by_id: dict[str, PlanStep],
    ) -> bool:
        return any(
            steps_by_id[dependency].status
            in {
                PlanStepStatus.FAILED,
                PlanStepStatus.SKIPPED,
                PlanStepStatus.CANCELLED,
            }
            for dependency in step.depends_on
        )

    async def execute(
        self,
        plan: ExecutionPlan,
        *,
        session_id: str,
        turn_id: str,
        cancellation_event: asyncio.Event
        | None = None,
        checkpoint_callback: Callable[
            [ExecutionPlan],
            Awaitable[None] | None,
        ]
        | None = None,
    ) -> PlanExecutionResult:
        validation = PlanValidator.validate(
            plan,
            self.registry,
            max_steps=self.budget.max_steps,
        )

        if not validation.valid:
            return PlanExecutionResult(
                success=False,
                plan=plan,
                completed_steps=0,
                failed_steps=0,
                skipped_steps=0,
                error_code="INVALID_PLAN",
                message=(
                    "План отклонён: "
                    + " ".join(validation.errors)
                ),
            )

        started_at = time.monotonic()

        steps_by_id = {
            step.step_id: step
            for step in plan.steps
        }

        # Completed steps come from a durable checkpoint and must never be
        # repeated after an application restart.
        unresolved = {
            step_id
            for step_id, step in steps_by_id.items()
            if step.status
            != PlanStepStatus.COMPLETED
        }

        # A process can die while a step is marked running. There is no
        # trustworthy completion result in that state, so it becomes pending.
        for step_id in unresolved:
            if (
                steps_by_id[step_id].status
                == PlanStepStatus.RUNNING
            ):
                steps_by_id[step_id].status = (
                    PlanStepStatus.PENDING
                )

        async def save_checkpoint() -> None:
            if checkpoint_callback is None:
                return
            result = checkpoint_callback(plan)
            if result is not None:
                await result

        await save_checkpoint()

        while unresolved:
            if (
                cancellation_event is not None
                and cancellation_event.is_set()
            ):
                for step_id in unresolved:
                    steps_by_id[
                        step_id
                    ].status = (
                        PlanStepStatus.CANCELLED
                    )

                await save_checkpoint()
                break

            elapsed = (
                time.monotonic() - started_at
            )

            if (
                elapsed
                >= self.budget.max_wall_time_seconds
            ):
                for step_id in unresolved:
                    steps_by_id[
                        step_id
                    ].status = (
                        PlanStepStatus.CANCELLED
                    )

                await save_checkpoint()
                return self._summarize(
                    plan,
                    error_code=(
                        "PLAN_TIME_BUDGET_EXHAUSTED"
                    ),
                    message=(
                        "План остановлен по лимиту времени."
                    ),
                )

            progress_made = False

            for step_id in list(unresolved):
                step = steps_by_id[step_id]

                if self._dependency_failed(
                    step,
                    steps_by_id,
                ):
                    step.status = (
                        PlanStepStatus.SKIPPED
                    )
                    unresolved.remove(step_id)
                    progress_made = True
                    await save_checkpoint()
                    continue

                if not self._dependencies_completed(
                    step,
                    steps_by_id,
                ):
                    continue

                step.status = PlanStepStatus.RUNNING
                await save_checkpoint()

                context = ToolContext.create(
                    session_id=session_id,
                    turn_id=turn_id,
                    source="plan_executor",
                    metadata={
                        "plan_id": plan.plan_id,
                        "step_id": step.step_id,
                        "goal": plan.goal,
                    },
                )

                if (
                    cancellation_event is not None
                    and cancellation_event.is_set()
                ):
                    context.cancellation.cancel()

                tool_call = self._build_tool_call(
                    step
                )

                logger.info(
                    "План %s: выполняется шаг %s, tool=%s",
                    plan.plan_id,
                    step.step_id,
                    step.tool_name,
                )

                async def execute_attempt(
                    attempt: int,
                ) -> ToolResult:
                    context.metadata[
                        "recovery_attempt"
                    ] = attempt

                    return await self.runner.execute(
                        tool_call,
                        context=context,
                    )

                result, recovery_decision = (
                    await self.recovery_engine.execute_with_recovery(
                        execute_attempt,
                        operation_name=step.tool_name,
                        max_attempts=3,
                        has_fallback=False,
                        has_rollback=(
                            bool(
                                self.registry.get(
                                    step.tool_name
                                ).supports_rollback
                            )
                            if self.registry.get(
                                step.tool_name
                            )
                            is not None
                            else False
                        ),
                        cancellation_event=(
                            cancellation_event
                        ),
                    )
                )

                context.metadata[
                    "recovery_action"
                ] = recovery_decision.action.value


                step.result = result

                verified, verification_message = (
                    StepVerifier.verify(
                        step,
                        result,
                    )
                )

                if verified:
                    step.status = (
                        PlanStepStatus.COMPLETED
                    )
                else:
                    step.status = (
                        PlanStepStatus.FAILED
                    )

                    logger.warning(
                        "Шаг %s завершился ошибкой: %s",
                        step.step_id,
                        verification_message,
                    )

                unresolved.remove(step_id)
                progress_made = True
                # This is the critical durable boundary: the verified result is
                # stored before another side-effecting step may start.
                await save_checkpoint()

                if (
                    step.status
                    == PlanStepStatus.FAILED
                    and step.critical
                ):
                    for pending_id in unresolved:
                        pending_step = steps_by_id[
                            pending_id
                        ]
                        pending_step.status = (
                            PlanStepStatus.SKIPPED
                        )

                    await save_checkpoint()
                    return self._summarize(
                        plan,
                        error_code=(
                            "CRITICAL_PLAN_STEP_FAILED"
                        ),
                        message=(
                            f"Критический шаг "
                            f"'{step.step_id}' "
                            "завершился ошибкой."
                        ),
                    )

            if not progress_made:
                return self._summarize(
                    plan,
                    error_code="PLAN_DEADLOCK",
                    message=(
                        "План не может продолжаться: "
                        "зависимости не разрешаются."
                    ),
                )

        return self._summarize(
            plan,
            message="План выполнен.",
        )

    @staticmethod
    def _summarize(
        plan: ExecutionPlan,
        *,
        error_code: str | None = None,
        message: str = "",
    ) -> PlanExecutionResult:
        completed = sum(
            step.status
            == PlanStepStatus.COMPLETED
            for step in plan.steps
        )
        failed = sum(
            step.status
            == PlanStepStatus.FAILED
            for step in plan.steps
        )
        skipped = sum(
            step.status
            in {
                PlanStepStatus.SKIPPED,
                PlanStepStatus.CANCELLED,
            }
            for step in plan.steps
        )

        success = (
            failed == 0
            and skipped == 0
            and completed == len(plan.steps)
        )

        return PlanExecutionResult(
            success=success,
            plan=plan,
            completed_steps=completed,
            failed_steps=failed,
            skipped_steps=skipped,
            error_code=(
                error_code
                if not success
                else None
            ),
            message=(
                message
                or (
                    "План выполнен успешно."
                    if success
                    else
                    "План завершён не полностью."
                )
            ),
        )
