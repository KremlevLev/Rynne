# modules/agent/background_plans.py
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from modules.agent.plan_service import PlanService
from modules.domain.results import ToolResult
from modules.storage.database import Database


logger = logging.getLogger("BackgroundPlans")


class BackgroundPlanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class BackgroundPlan:
    background_id: str
    goal: str
    steps: list[dict[str, Any]]

    session_id: str
    turn_id: str
    plan_id: str

    status: BackgroundPlanStatus = (
        BackgroundPlanStatus.QUEUED
    )

    created_at: float = field(
        default_factory=time.time
    )
    started_at: float | None = None
    finished_at: float | None = None

    result: ToolResult | None = None
    error: str | None = None
    recovered: bool = False
    attempts: int = 0

    task: asyncio.Task[None] | None = field(
        default=None,
        repr=False,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "background_id": self.background_id,
            "goal": self.goal,
            "steps_count": len(self.steps),
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "plan_id": self.plan_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": (
                self.result.to_dict()
                if self.result is not None
                else None
            ),
            "error": self.error,
            "recovered": self.recovered,
            "attempts": self.attempts,
        }

    def to_payload(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload["steps"] = self.steps
        return payload


class BackgroundPlanManager:
    """
    Запускает PlanService в фоновых asyncio-задачах.

    Пользователь может:
    - получить status;
    - перечислить задачи;
    - отменить задачу;
    - продолжать общаться с Nova, пока план выполняется.
    """

    def __init__(
        self,
        plan_service: PlanService,
        database: Database | None = None,
    ) -> None:
        self.plan_service = plan_service
        self.database = database

        self._plans: dict[
            str,
            BackgroundPlan,
        ] = {}

        self._lock = asyncio.Lock()
        self._closed = False
        self._load_persisted_plans()
        self._resume_loaded_plans()

    @staticmethod
    def _result_from_dict(raw: Any) -> ToolResult | None:
        if not isinstance(raw, dict):
            return None
        return ToolResult(
            success=bool(raw.get("success")),
            code=str(raw.get("code") or "OK"),
            message=str(raw.get("message") or ""),
            data=(
                raw.get("data")
                if isinstance(raw.get("data"), dict)
                else {}
            ),
        )

    def _load_persisted_plans(self) -> None:
        if self.database is None:
            return
        rows = self.database.fetchall(
            "SELECT payload FROM background_plans"
        )
        for row in rows:
            try:
                payload = json.loads(row["payload"])
                status = BackgroundPlanStatus(payload["status"])
                if status in {
                    BackgroundPlanStatus.QUEUED,
                    BackgroundPlanStatus.RUNNING,
                }:
                    status = BackgroundPlanStatus.QUEUED
                elif status == BackgroundPlanStatus.CANCELLING:
                    # A persisted user cancellation must never turn back into
                    # an executable side effect after a restart.
                    status = BackgroundPlanStatus.CANCELLED
                record = BackgroundPlan(
                    background_id=payload["background_id"],
                    goal=payload["goal"],
                    steps=payload.get("steps", []),
                    session_id=payload["session_id"],
                    turn_id=payload["turn_id"],
                    plan_id=(
                        payload.get("plan_id")
                        or f"plan_{payload['background_id']}"
                    ),
                    status=status,
                    created_at=float(payload["created_at"]),
                    started_at=payload.get("started_at"),
                    finished_at=payload.get("finished_at"),
                    result=self._result_from_dict(payload.get("result")),
                    error=payload.get("error"),
                    recovered=True,
                    attempts=int(
                        payload.get("attempts")
                        or (
                            1
                            if payload.get("started_at") is not None
                            else 0
                        )
                    ),
                )
                self._plans[record.background_id] = record
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                logger.exception(
                    "Повреждён checkpoint фонового плана."
                )

    def _resume_loaded_plans(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        for record in self._plans.values():
            if record.status == BackgroundPlanStatus.QUEUED:
                record.task = asyncio.create_task(
                    self._run_plan(record),
                    name=(
                        "nova-background-plan-"
                        f"{record.background_id}"
                    ),
                )

    def _persist(self, record: BackgroundPlan) -> None:
        if self.database is None:
            return
        self.database.execute(
            """
            INSERT INTO background_plans (
                background_id, payload, updated_at
            ) VALUES (?, ?, datetime('now'))
            ON CONFLICT(background_id) DO UPDATE SET
                payload=excluded.payload,
                updated_at=datetime('now')
            """,
            (
                record.background_id,
                json.dumps(record.to_payload(), ensure_ascii=False),
            ),
        )
        self.database.commit()

    async def start_plan(
        self,
        goal: str,
        steps: list[dict[str, Any]],
        *,
        session_id: str = "background-session",
        turn_id: str | None = None,
    ) -> ToolResult:
        if self._closed:
            return ToolResult.failure(
                "BACKGROUND_MANAGER_CLOSED",
                "Менеджер фоновых планов закрыт.",
            )

        if not goal.strip():
            return ToolResult.failure(
                "EMPTY_PLAN_GOAL",
                "Цель фонового плана не указана.",
            )

        if not isinstance(steps, list) or not steps:
            return ToolResult.failure(
                "INVALID_PLAN_STEPS",
                (
                    "Фоновый план должен содержать "
                    "хотя бы один шаг."
                ),
            )

        background_id = (
            f"background_{uuid.uuid4().hex}"
        )

        resolved_turn_id = (
            turn_id
            or f"background_turn_{uuid.uuid4().hex}"
        )

        record = BackgroundPlan(
            background_id=background_id,
            goal=goal.strip(),
            steps=steps,
            session_id=session_id,
            turn_id=resolved_turn_id,
            plan_id=f"plan_{background_id}",
        )

        async with self._lock:
            self._plans[background_id] = record
            self._persist(record)

            record.task = asyncio.create_task(
                self._run_plan(record),
                name=(
                    f"nova-background-plan-"
                    f"{background_id}"
                ),
            )

        return ToolResult.ok(
            (
                "Фоновый план поставлен в очередь. "
                f"Идентификатор: {background_id}."
            ),
            data={
                "background_id": background_id,
                "status": record.status.value,
                "goal": record.goal,
                "steps_count": len(steps),
            },
        )

    async def _run_plan(
        self,
        record: BackgroundPlan,
    ) -> None:
        record.attempts += 1
        record.status = BackgroundPlanStatus.RUNNING
        record.started_at = time.time()
        record.finished_at = None
        self._persist(record)

        logger.info(
            "Фоновый план запущен: %s goal=%s",
            record.background_id,
            record.goal,
        )

        try:
            async def checkpoint(plan) -> None:
                record.steps = plan.to_dict()["steps"]
                self._persist(record)

            parameters = inspect.signature(
                self.plan_service.execute_plan
            ).parameters
            extra_arguments = {}
            if "plan_id" in parameters:
                extra_arguments["plan_id"] = record.plan_id
            if "checkpoint_callback" in parameters:
                extra_arguments["checkpoint_callback"] = checkpoint

            result = await self.plan_service.execute_plan(
                goal=record.goal,
                steps=record.steps,
                session_id=record.session_id,
                turn_id=record.turn_id,
                **extra_arguments,
            )

            record.result = result

            if (
                self._closed
                and record.status
                == BackgroundPlanStatus.QUEUED
            ):
                record.result = None
            elif record.status == (
                BackgroundPlanStatus.CANCELLING
            ):
                record.status = (
                    BackgroundPlanStatus.CANCELLED
                )
            elif result.success:
                record.status = (
                    BackgroundPlanStatus.COMPLETED
                )
            else:
                record.status = (
                    BackgroundPlanStatus.FAILED
                )

        except asyncio.CancelledError:
            if (
                self._closed
                and record.status
                != BackgroundPlanStatus.CANCELLING
            ):
                # Shutdown is not a user cancellation. Leave the durable
                # checkpoint queued for the next Nova process.
                record.status = BackgroundPlanStatus.QUEUED
                record.finished_at = None
                record.result = None
                raise

            record.status = (
                BackgroundPlanStatus.CANCELLED
            )

            record.result = ToolResult.failure(
                "BACKGROUND_PLAN_CANCELLED",
                "Фоновый план отменён.",
            )

            raise

        except Exception as exc:
            logger.exception(
                "Фоновый план %s упал.",
                record.background_id,
            )

            record.status = (
                BackgroundPlanStatus.FAILED
            )
            record.error = str(exc)

            record.result = ToolResult.failure(
                "BACKGROUND_PLAN_FAILED",
                (
                    "Фоновый план завершился "
                    f"необработанной ошибкой: {exc}"
                ),
            )

        finally:
            if record.status != BackgroundPlanStatus.QUEUED:
                record.finished_at = time.time()
            self._persist(record)

            logger.info(
                "Фоновый план завершён: %s status=%s",
                record.background_id,
                record.status.value,
            )

    async def get_status(
        self,
        background_id: str,
    ) -> ToolResult:
        async with self._lock:
            record = self._plans.get(
                background_id
            )

        if record is None:
            return ToolResult.failure(
                "BACKGROUND_PLAN_NOT_FOUND",
                (
                    f"Фоновый план '{background_id}' "
                    "не найден."
                ),
            )

        return ToolResult.ok(
            (
                f"Статус фонового плана: "
                f"{record.status.value}."
            ),
            data=record.to_dict(),
        )

    async def list_plans(self) -> ToolResult:
        async with self._lock:
            records = list(
                self._plans.values()
            )

        records.sort(
            key=lambda item: item.created_at,
            reverse=True,
        )

        return ToolResult.ok(
            (
                f"Найдено фоновых планов: "
                f"{len(records)}."
            ),
            data={
                "count": len(records),
                "plans": [
                    record.to_dict()
                    for record in records
                ],
            },
        )

    async def cancel_plan(
        self,
        background_id: str,
    ) -> ToolResult:
        """
        Отменяет активный фоновый план.

        Статус устанавливается явно после ожидания task, потому что
        asyncio-задача может быть отменена ещё до запуска _run_plan().
        В таком случае её внутренний обработчик CancelledError не
        успевает изменить состояние.
        """
        async with self._lock:
            record = self._plans.get(
                background_id
            )

            if record is None:
                return ToolResult.failure(
                    "BACKGROUND_PLAN_NOT_FOUND",
                    (
                        f"Фоновый план '{background_id}' "
                        "не найден."
                    ),
                )

            if record.status in {
                BackgroundPlanStatus.COMPLETED,
                BackgroundPlanStatus.FAILED,
                BackgroundPlanStatus.CANCELLED,
            }:
                return ToolResult.ok(
                    (
                        "Фоновый план уже завершён. "
                        f"Статус: {record.status.value}."
                    ),
                    data=record.to_dict(),
                )

            record.status = (
                BackgroundPlanStatus.CANCELLING
            )
            self._persist(record)
            task = record.task

        # Task отменяется за пределами lock, чтобы _run_plan()
        # мог безопасно обновить собственное состояние.
        if task is not None and not task.done():
            task.cancel()

            await asyncio.gather(
                task,
                return_exceptions=True,
            )

        # Если задача была отменена до фактического запуска
        # _run_plan(), её except/finally не исполнятся.
        # Поэтому гарантированно завершаем переход состояния здесь.
        async with self._lock:
            if record.status in {
                BackgroundPlanStatus.QUEUED,
                BackgroundPlanStatus.RUNNING,
                BackgroundPlanStatus.CANCELLING,
            }:
                record.status = (
                    BackgroundPlanStatus.CANCELLED
                )

            if record.finished_at is None:
                record.finished_at = time.time()

            if record.result is None:
                record.result = ToolResult.failure(
                    "BACKGROUND_PLAN_CANCELLED",
                    "Фоновый план отменён.",
                )

            result_data = record.to_dict()
            self._persist(record)

        logger.info(
            "Фоновый план отменён: %s",
            background_id,
        )

        return ToolResult.ok(
            f"Фоновый план '{background_id}' отменён.",
            data=result_data,
        )

    async def retry_plan(
        self,
        background_id: str,
    ) -> ToolResult:
        """Повторяет failed-план, сохраняя completed checkpoints."""
        async with self._lock:
            record = self._plans.get(background_id)
            if record is None:
                return ToolResult.failure(
                    "BACKGROUND_PLAN_NOT_FOUND",
                    (
                        f"Фоновый план '{background_id}' "
                        "не найден."
                    ),
                )

            if record.status != BackgroundPlanStatus.FAILED:
                return ToolResult.failure(
                    "BACKGROUND_PLAN_NOT_RETRYABLE",
                    (
                        "Повторить можно только failed-план. "
                        f"Текущий статус: {record.status.value}."
                    ),
                )

            if record.task is not None and not record.task.done():
                return ToolResult.failure(
                    "BACKGROUND_PLAN_STILL_ACTIVE",
                    "Фоновый план ещё выполняется.",
                )

            record.status = BackgroundPlanStatus.QUEUED
            record.error = None
            record.result = None
            record.finished_at = None
            self._persist(record)
            record.task = asyncio.create_task(
                self._run_plan(record),
                name=(
                    "nova-background-plan-"
                    f"{record.background_id}-retry"
                ),
            )

            result_data = record.to_dict()

        return ToolResult.ok(
            (
                f"Фоновый план '{background_id}' "
                "поставлен на повторное выполнение."
            ),
            data=result_data,
        )


    async def close(self) -> None:
        self._closed = True

        async with self._lock:
            for record in self._plans.values():
                if record.status in {
                    BackgroundPlanStatus.QUEUED,
                    BackgroundPlanStatus.RUNNING,
                }:
                    record.status = BackgroundPlanStatus.QUEUED
                    record.finished_at = None
                    self._persist(record)

            tasks = [
                record.task
                for record in self._plans.values()
                if (
                    record.task is not None
                    and not record.task.done()
                )
            ]

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        logger.info(
            "Менеджер фоновых планов закрыт."
        )
