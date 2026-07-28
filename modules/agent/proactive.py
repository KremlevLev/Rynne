from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Mapping
from typing import Any, Callable, Iterable

from modules.agent.background_plans import (
    BackgroundPlan,
    BackgroundPlanStatus,
)
from modules.storage.database import Database


@dataclass(frozen=True, slots=True)
class ProactiveSuggestion:
    event_id: str
    kind: str
    title: str
    message: str
    reason: str
    source_key: str
    importance: str = "normal"

    def to_dict(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "title": self.title,
            "message": self.message,
            "reason": self.reason,
            "source_key": self.source_key,
            "importance": self.importance,
        }


class ProactiveSuggestionEngine:
    """Creates suggestions from explicit local triggers; never takes action."""

    def __init__(
        self,
        database: Database,
        *,
        cooldown_seconds: float = 60.0,
        quiet_hours: tuple[int, int] = (22, 8),
        clock: Callable[[], float] = time.time,
        local_hour: Callable[[], int] | None = None,
    ) -> None:
        self.database = database
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.quiet_hours = quiet_hours
        self.clock = clock
        self.local_hour = (
            local_hour
            or (lambda: datetime.now().astimezone().hour)
        )
        self._last_emitted: dict[str, float] = {}

    def _is_quiet_time(self) -> bool:
        start, end = self.quiet_hours
        hour = self.local_hour()
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def _was_emitted(self, source_key: str) -> bool:
        return self.database.fetchone(
            """
            SELECT event_id FROM proactive_events
            WHERE source_key = ?
            """,
            (source_key,),
        ) is not None

    def _store(self, suggestion: ProactiveSuggestion) -> None:
        self.database.execute(
            """
            INSERT OR IGNORE INTO proactive_events (
                event_id, source_key, kind, payload
            ) VALUES (?, ?, ?, ?)
            """,
            (
                suggestion.event_id,
                suggestion.source_key,
                suggestion.kind,
                json.dumps(
                    suggestion.to_dict(),
                    ensure_ascii=False,
                ),
            ),
        )
        self.database.commit()

    def observe_background_plans(
        self,
        plans: Iterable[BackgroundPlan],
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        now = self.clock()
        suggestions: list[ProactiveSuggestion] = []
        for plan in plans:
            if plan.status not in {
                BackgroundPlanStatus.COMPLETED,
                BackgroundPlanStatus.FAILED,
            }:
                continue

            kind = (
                "background_plan_completed"
                if plan.status == BackgroundPlanStatus.COMPLETED
                else "background_plan_failed"
            )
            source_key = (
                f"background:{plan.background_id}:{plan.status.value}"
            )
            if self._was_emitted(source_key):
                continue

            last_emitted = self._last_emitted.get(kind, 0.0)
            if now - last_emitted < self.cooldown_seconds:
                continue

            if plan.status == BackgroundPlanStatus.COMPLETED:
                title = "Фоновая задача завершена"
                message = f"Готово: {plan.goal}"
                reason = (
                    "План сообщил подтверждённый статус completed."
                )
                importance = "normal"
            else:
                title = "Фоновая задача остановилась"
                message = f"Не удалось завершить: {plan.goal}"
                reason = (
                    "План сообщил статус failed"
                    + (f": {plan.error}" if plan.error else ".")
                )
                importance = "high"

            suggestion = ProactiveSuggestion(
                event_id=f"proactive_{uuid.uuid4().hex}",
                kind=kind,
                title=title,
                message=message,
                reason=reason,
                source_key=source_key,
                importance=importance,
            )
            self._store(suggestion)
            self._last_emitted[kind] = now
            suggestions.append(suggestion)

        return suggestions

    def observe_processes(
        self,
        processes: Iterable[Mapping[str, Any]],
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        now = self.clock()
        suggestions: list[ProactiveSuggestion] = []
        for process in processes:
            status = str(process.get("status") or "")
            if status != "exited":
                continue

            process_id = str(process.get("process_id") or "")
            if not process_id:
                continue
            exit_code = process.get("exit_code")
            source_key = (
                f"process:{process_id}:{status}:{exit_code}"
            )
            if self._was_emitted(source_key):
                continue

            label = str(
                process.get("label")
                or process_id
            )
            raw_command = process.get("command")
            command = " ".join(
                str(item)
                for item in raw_command
            ) if isinstance(raw_command, list) else str(
                raw_command or ""
            )
            searchable = f"{label} {command}".lower()
            is_test = any(
                marker in searchable
                for marker in (
                    "pytest",
                    "unittest",
                    "npm test",
                    "pnpm test",
                    "cargo test",
                )
            )
            is_server = (
                bool(process.get("health_check_url"))
                or bool(process.get("health_check_port"))
                or any(
                    marker in searchable
                    for marker in (
                        "server",
                        "uvicorn",
                        "gunicorn",
                        "http.server",
                        "vite",
                    )
                )
            )
            succeeded = exit_code == 0

            if is_test and succeeded:
                kind = "tests_completed"
                title = "Тесты завершены"
                message = f"{label}: тестовый процесс завершился успешно."
                importance = "normal"
            elif is_server and not succeeded:
                kind = "server_stopped"
                title = "Сервер остановился"
                message = (
                    f"{label} завершился с кодом {exit_code}."
                )
                importance = "high"
            elif succeeded:
                kind = "process_completed"
                title = "Фоновый процесс завершён"
                message = f"{label} завершился успешно."
                importance = "normal"
            else:
                kind = "process_failed"
                title = "Фоновый процесс завершился с ошибкой"
                message = (
                    f"{label} завершился с кодом {exit_code}."
                )
                importance = "high"

            last_emitted = self._last_emitted.get(kind, 0.0)
            if now - last_emitted < self.cooldown_seconds:
                continue

            suggestion = ProactiveSuggestion(
                event_id=f"proactive_{uuid.uuid4().hex}",
                kind=kind,
                title=title,
                message=message,
                reason=(
                    "ProcessManager зафиксировал переход "
                    f"running → exited; exit_code={exit_code}."
                ),
                source_key=source_key,
                importance=importance,
            )
            self._store(suggestion)
            self._last_emitted[kind] = now
            suggestions.append(suggestion)

        return suggestions

    def journal(self, limit: int = 100) -> list[dict]:
        rows = self.database.fetchall(
            """
            SELECT payload FROM proactive_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(1000, int(limit))),),
        )
        return [json.loads(row["payload"]) for row in rows]
