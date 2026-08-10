from __future__ import annotations

import json
import hashlib
import shutil
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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
    suggested_request: str | None = None
    action_label: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "event_id": self.event_id,
            "kind": self.kind,
            "title": self.title,
            "message": self.message,
            "reason": self.reason,
            "source_key": self.source_key,
            "importance": self.importance,
        }
        if self.suggested_request:
            payload["suggested_request"] = (
                self.suggested_request
            )
        if self.action_label:
            payload["action_label"] = self.action_label
        return payload


class ProactiveSuggestionEngine:
    """Creates suggestions from explicit local triggers; never takes action."""

    def __init__(
        self,
        database: Database,
        *,
        cooldown_seconds: float = 60.0,
        quiet_hours: tuple[int, int] = (22, 8),
        disabled_kinds: Iterable[str] = (),
        clock: Callable[[], float] = time.time,
        local_hour: Callable[[], int] | None = None,
    ) -> None:
        self.database = database
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.quiet_hours = quiet_hours
        self.disabled_kinds = frozenset(disabled_kinds)
        self.clock = clock
        self.local_hour = (
            local_hour
            or (lambda: datetime.now().astimezone().hour)
        )
        self._last_emitted: dict[str, float] = {}

    def _kind_enabled(self, kind: str) -> bool:
        if kind in self.disabled_kinds:
            return False
        feedback = self._get_state(
            f"proactive_feedback_kind:{kind}"
        )
        return float(feedback.get("muted_until") or 0.0) <= self.clock()

    def record_feedback(
        self,
        event_id: str,
        feedback: str,
        *,
        source: str = "unknown",
    ) -> dict[str, Any]:
        """Learns notification tolerance without storing user content."""
        normalized = str(feedback).casefold().strip()
        if normalized not in {"accepted", "dismissed"}:
            raise ValueError("Неизвестная реакция на proactive-подсказку.")
        row = self.database.fetchone(
            "SELECT kind FROM proactive_events WHERE event_id = ?",
            (str(event_id),),
        )
        if row is None:
            raise ValueError("Proactive-подсказка не найдена.")

        kind = str(row["kind"])
        state_key = f"proactive_feedback_kind:{kind}"
        state = self._get_state(state_key)
        score = int(state.get("score") or 0)
        accepted = int(state.get("accepted") or 0)
        dismissed = int(state.get("dismissed") or 0)
        muted_until = float(state.get("muted_until") or 0.0)
        if normalized == "accepted":
            accepted += 1
            score = min(4, score + 2)
            muted_until = 0.0
        else:
            dismissed += 1
            score -= 1
            if score <= -3:
                muted_until = self.clock() + 6 * 60 * 60
                score = 0

        updated = {
            "kind": kind,
            "score": score,
            "accepted": accepted,
            "dismissed": dismissed,
            "muted_until": muted_until,
            "last_feedback": normalized,
            "last_source": str(source),
            "last_event_id": str(event_id),
        }
        self._set_state(state_key, updated)
        self._set_state(
            f"proactive_feedback_event:{event_id}",
            {
                "feedback": normalized,
                "source": str(source),
                "recorded_at": self.clock(),
            },
        )
        return updated

    def can_observe(
        self,
        kind: str,
        *,
        ignore_quiet_hours: bool = False,
    ) -> bool:
        """Whether an expensive observer may run right now."""
        return (
            self._kind_enabled(kind)
            and (
                ignore_quiet_hours
                or not self._is_quiet_time()
            )
        )

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

    def _get_state(self, state_key: str) -> dict[str, Any]:
        row = self.database.fetchone(
            """
            SELECT value FROM proactive_state
            WHERE state_key = ?
            """,
            (state_key,),
        )
        if row is None:
            return {}
        try:
            value = json.loads(row["value"])
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _set_state(
        self,
        state_key: str,
        value: Mapping[str, Any],
    ) -> None:
        self.database.execute(
            """
            INSERT INTO proactive_state (state_key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(state_key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (
                state_key,
                json.dumps(dict(value), ensure_ascii=False),
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
            if not self._kind_enabled(kind):
                continue
            source_key = (
                f"background:{plan.background_id}:{plan.status.value}"
            )
            if (
                plan.status == BackgroundPlanStatus.FAILED
                and plan.attempts > 1
            ):
                source_key += f":attempt:{plan.attempts}"
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

    def observe_incomplete_plans(
        self,
        plans: Iterable[BackgroundPlan],
        *,
        suggest_after_seconds: float = 15 * 60,
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        kind = "background_plan_resume_suggested"
        if not self._kind_enabled(kind):
            return []

        now = self.clock()
        suggestions: list[ProactiveSuggestion] = []
        for plan in plans:
            if (
                plan.status != BackgroundPlanStatus.FAILED
                or plan.finished_at is None
            ):
                continue
            if (
                now - plan.finished_at
                < max(0.0, suggest_after_seconds)
            ):
                continue

            attempt = max(1, plan.attempts)
            source_key = (
                f"background:{plan.background_id}:"
                f"resume-suggested:{attempt}"
            )
            if self._was_emitted(source_key):
                continue
            if (
                now - self._last_emitted.get(kind, 0.0)
                < self.cooldown_seconds
            ):
                continue

            suggestion = ProactiveSuggestion(
                event_id=f"proactive_{uuid.uuid4().hex}",
                kind=kind,
                title="Продолжить незавершённую задачу?",
                message=(
                    f"{plan.goal} — можно повторить failed-шаг "
                    "с последнего checkpoint."
                ),
                reason=(
                    "План остался в статусе failed после паузы; "
                    "completed-шаги сохранены и не будут повторены."
                ),
                source_key=source_key,
                importance="normal",
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
            # Do not replay old completions restored from metadata at startup.
            if bool(process.get("restored")):
                continue
            status = str(process.get("status") or "")
            if status != "exited":
                continue

            process_id = str(process.get("process_id") or "")
            if not process_id:
                continue
            exit_code = process.get("exit_code")
            # A restored process has no Popen handle, so its exact exit code
            # cannot be recovered. Do not label an unknown code as failure.
            if exit_code is None:
                continue
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

            if not self._kind_enabled(kind):
                continue
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

    def observe_disk_space(
        self,
        path: str | Path,
        *,
        free_percent_threshold: float = 10.0,
        free_bytes_threshold: int = 5 * 1024**3,
        usage: tuple[int, int, int] | None = None,
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        resolved = Path(path).resolve()
        volume = resolved.anchor or str(resolved)
        total, _used, free = usage or shutil.disk_usage(resolved)
        free_percent = (free / total * 100.0) if total else 0.0
        is_low = (
            free_percent <= max(0.0, free_percent_threshold)
            or free <= max(0, free_bytes_threshold)
        )
        state_key = f"disk_space:{volume.casefold()}"
        previous = self._get_state(state_key)
        cycle = int(previous.get("cycle", 0))

        if not is_low:
            if previous.get("status") != "normal":
                self._set_state(
                    state_key,
                    {"status": "normal", "cycle": cycle},
                )
            return []

        if previous.get("status") == "low":
            return []

        kind = "disk_space_low"
        if not self._kind_enabled(kind):
            return []

        now = self.clock()
        if (
            now - self._last_emitted.get(kind, 0.0)
            < self.cooldown_seconds
        ):
            return []

        cycle += 1
        source_key = f"disk:{volume.casefold()}:low:{cycle}"
        if self._was_emitted(source_key):
            self._set_state(
                state_key,
                {"status": "low", "cycle": cycle},
            )
            return []

        free_gib = free / 1024**3
        suggestion = ProactiveSuggestion(
            event_id=f"proactive_{uuid.uuid4().hex}",
            kind=kind,
            title="Заканчивается место на диске",
            message=(
                f"На диске {volume} осталось "
                f"{free_gib:.1f} ГБ ({free_percent:.1f}%)."
            ),
            reason=(
                "Свободное место пересекло настроенный порог: "
                f"{free_percent_threshold:.1f}% или "
                f"{free_bytes_threshold / 1024**3:.1f} ГБ."
            ),
            source_key=source_key,
            importance="high",
        )
        self._store(suggestion)
        self._set_state(
            state_key,
            {"status": "low", "cycle": cycle},
        )
        self._last_emitted[kind] = now
        return [suggestion]

    def observe_system_health(
        self,
        snapshot: Mapping[str, Any],
        *,
        cpu_percent_threshold: float = 90.0,
        memory_percent_threshold: float = 88.0,
        consecutive_samples: int = 4,
        max_sample_gap_seconds: float = 60.0,
    ) -> list[ProactiveSuggestion]:
        """Alerts only after sustained pressure and names the likely culprit."""
        if self._is_quiet_time():
            return []

        kind = "system_resource_pressure"
        if not self._kind_enabled(kind):
            return []

        cpu_percent = max(
            0.0,
            float(snapshot.get("cpu_percent") or 0.0),
        )
        memory_percent = max(
            0.0,
            float(snapshot.get("memory_percent") or 0.0),
        )
        sampled_at = float(
            snapshot.get("sampled_at") or self.clock()
        )
        cpu_limit = max(1.0, cpu_percent_threshold)
        memory_limit = max(
            1.0,
            memory_percent_threshold,
        )
        is_high = (
            cpu_percent >= cpu_limit
            or memory_percent >= memory_limit
        )

        state_key = "system_health:resource_pressure"
        previous = self._get_state(state_key)
        cycle = int(previous.get("cycle", 0))
        streak = int(previous.get("streak", 0))
        active = bool(previous.get("active", False))
        previous_sampled_at = float(
            previous.get("sampled_at", 0.0)
        )

        if (
            previous_sampled_at
            and sampled_at - previous_sampled_at
            > max(1.0, max_sample_gap_seconds)
        ):
            streak = 0

        recovered = (
            cpu_percent < max(0.0, cpu_limit - 15.0)
            and memory_percent
            < max(0.0, memory_limit - 10.0)
        )
        if not is_high:
            if recovered and (active or streak):
                self._set_state(
                    state_key,
                    {
                        "active": False,
                        "streak": 0,
                        "cycle": cycle,
                        "sampled_at": sampled_at,
                    },
                )
            return []

        if active:
            return []

        streak += 1
        state = {
            "active": active,
            "streak": streak,
            "cycle": cycle,
            "sampled_at": sampled_at,
        }
        if active or streak < max(1, consecutive_samples):
            self._set_state(state_key, state)
            return []

        now = self.clock()
        if (
            now - self._last_emitted.get(kind, 0.0)
            < self.cooldown_seconds
        ):
            self._set_state(state_key, state)
            return []

        cycle += 1
        source_key = f"system:resource-pressure:{cycle}"
        if self._was_emitted(source_key):
            state.update({"active": True, "cycle": cycle})
            self._set_state(state_key, state)
            return []

        high_resources: list[str] = []
        if cpu_percent >= cpu_limit:
            high_resources.append(
                f"CPU {cpu_percent:.0f}%"
            )
        if memory_percent >= memory_limit:
            high_resources.append(
                f"RAM {memory_percent:.0f}%"
            )

        top_processes = snapshot.get(
            "top_processes",
            [],
        )
        culprit = None
        if isinstance(top_processes, list):
            candidates = [
                item
                for item in top_processes
                if isinstance(item, Mapping)
            ]
            if candidates:
                prefer_memory = (
                    memory_percent >= memory_limit
                    and cpu_percent < cpu_limit
                )
                culprit = max(
                    candidates,
                    key=lambda item: float(
                        item.get(
                            "memory_percent"
                            if prefer_memory
                            else "cpu_percent",
                            0.0,
                        )
                        or 0.0
                    ),
                )

        culprit_text = ""
        if culprit is not None:
            culprit_text = (
                " Больше всего ресурсов использует "
                f"{str(culprit.get('name') or 'процесс')} "
                f"(PID {int(culprit.get('pid') or 0)}, "
                f"CPU {float(culprit.get('cpu_percent') or 0):.0f}%, "
                f"RAM {float(culprit.get('memory_percent') or 0):.1f}%)."
            )

        suggestion = ProactiveSuggestion(
            event_id=f"proactive_{uuid.uuid4().hex}",
            kind=kind,
            title="Система долго работает под высокой нагрузкой",
            message=(
                f"{' и '.join(high_resources)} держатся выше порога."
                f"{culprit_text}"
            ),
            reason=(
                "Высокая нагрузка подтверждена "
                f"{streak} последовательными измерениями; "
                f"пороги CPU={cpu_limit:.0f}% и "
                f"RAM={memory_limit:.0f}%."
            ),
            source_key=source_key,
            importance="high",
        )
        self._store(suggestion)
        self._last_emitted[kind] = now
        state.update({"active": True, "cycle": cycle})
        self._set_state(state_key, state)
        return [suggestion]

    def observe_visual_insight(
        self,
        insight: Any,
        *,
        ignore_quiet_hours: bool = False,
        force: bool = False,
    ) -> list[ProactiveSuggestion]:
        """Persists a safe vision insight without storing its screenshot."""
        if (
            self._is_quiet_time()
            and not ignore_quiet_hours
        ):
            return []
        kind = "proactive_visual_help"
        if not self._kind_enabled(kind):
            return []
        if not bool(
            getattr(insight, "should_interrupt", False)
        ):
            return []

        fingerprint = str(
            getattr(insight, "visual_fingerprint", "")
        ).strip()
        if not fingerprint:
            return []
        source_key = f"visual:{fingerprint}"
        already_emitted = self._was_emitted(source_key)
        if already_emitted and not force:
            return []

        now = self.clock()
        if (
            not force
            and
            now - self._last_emitted.get(kind, 0.0)
            < self.cooldown_seconds
        ):
            return []

        suggestion = ProactiveSuggestion(
            event_id=f"proactive_{uuid.uuid4().hex}",
            kind=kind,
            title=str(insight.title),
            message=str(insight.message),
            reason=str(insight.reason),
            source_key=source_key,
            importance="normal",
            suggested_request=str(
                insight.suggested_request
            ),
            action_label=str(insight.action_label),
        )
        if not already_emitted:
            self._store(suggestion)
        self._last_emitted[kind] = now
        return [suggestion]

    def observe_stale_processes(
        self,
        processes: Iterable[Mapping[str, Any]],
        *,
        stale_after_seconds: float = 4 * 60 * 60,
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        kind = "stale_process"
        if not self._kind_enabled(kind):
            return []

        now = self.clock()
        suggestions: list[ProactiveSuggestion] = []
        for process in processes:
            if bool(process.get("restored")):
                continue
            if str(process.get("status") or "") != "running":
                continue

            process_id = str(process.get("process_id") or "")
            started_at = str(process.get("started_at") or "")
            if not process_id or not started_at:
                continue

            raw_command = process.get("command")
            command = " ".join(
                str(item)
                for item in raw_command
            ) if isinstance(raw_command, list) else str(
                raw_command or ""
            )
            label = str(process.get("label") or process_id)
            searchable = f"{label} {command}".lower()
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
            if is_server:
                continue

            try:
                started = datetime.fromisoformat(
                    started_at.replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)

            age_seconds = max(0.0, now - started.timestamp())
            if age_seconds < max(0.0, stale_after_seconds):
                continue

            source_key = f"process:{process_id}:stale"
            if self._was_emitted(source_key):
                continue
            if (
                now - self._last_emitted.get(kind, 0.0)
                < self.cooldown_seconds
            ):
                continue

            age_hours = age_seconds / 3600
            suggestion = ProactiveSuggestion(
                event_id=f"proactive_{uuid.uuid4().hex}",
                kind=kind,
                title="Процесс всё ещё работает",
                message=(
                    f"{label} запущен уже {age_hours:.1f} ч. "
                    "Остановить его?"
                ),
                reason=(
                    "Управляемый процесс превысил настроенное время "
                    "работы и не похож на долгоживущий сервер."
                ),
                source_key=source_key,
                importance="normal",
            )
            self._store(suggestion)
            self._last_emitted[kind] = now
            suggestions.append(suggestion)

        return suggestions

    def observe_repository(
        self,
        repo_path: str | Path,
        status_text: str,
        *,
        uncommitted_after_seconds: float = 30 * 60,
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        resolved = Path(repo_path).resolve()
        repo_key = str(resolved).casefold()
        state_key = f"repository:{repo_key}"
        previous = self._get_state(state_key)
        cycle = int(previous.get("cycle", 0))
        lines = [
            line
            for line in status_text.splitlines()
            if line.strip()
        ]

        if not lines:
            if previous.get("status") != "clean":
                self._set_state(
                    state_key,
                    {"status": "clean", "cycle": cycle},
                )
            return []

        now = self.clock()
        if previous.get("status") != "dirty":
            cycle += 1
            state: dict[str, Any] = {
                "status": "dirty",
                "cycle": cycle,
                "first_seen": now,
                "conflict_notified": False,
                "commit_notified": False,
            }
        else:
            state = dict(previous)

        conflict_codes = {
            "DD",
            "AU",
            "UD",
            "UA",
            "DU",
            "AA",
            "UU",
        }
        has_conflicts = any(
            line[:2] in conflict_codes
            for line in lines
        )
        suggestions: list[ProactiveSuggestion] = []

        if (
            has_conflicts
            and not bool(state.get("conflict_notified"))
            and self._kind_enabled("repository_conflict")
        ):
            kind = "repository_conflict"
            if (
                now - self._last_emitted.get(kind, 0.0)
                >= self.cooldown_seconds
            ):
                suggestion = ProactiveSuggestion(
                    event_id=f"proactive_{uuid.uuid4().hex}",
                    kind=kind,
                    title="В репозитории есть конфликт",
                    message=(
                        f"{resolved.name}: Git сообщает о "
                        "неразрешённых конфликтах."
                    ),
                    reason=(
                        "В `git status --short` обнаружен conflict "
                        "status. Nova ничего не изменяла автоматически."
                    ),
                    source_key=(
                        f"repo:{repo_key}:conflict:{cycle}"
                    ),
                    importance="high",
                )
                self._store(suggestion)
                self._last_emitted[kind] = now
                state["conflict_notified"] = True
                suggestions.append(suggestion)

        first_seen = float(state.get("first_seen", now))
        dirty_age = max(0.0, now - first_seen)
        should_suggest_commit = (
            not has_conflicts
            and dirty_age
            >= max(0.0, uncommitted_after_seconds)
            and not bool(state.get("commit_notified"))
            and self._kind_enabled("repository_uncommitted")
        )
        if should_suggest_commit:
            kind = "repository_uncommitted"
            if (
                now - self._last_emitted.get(kind, 0.0)
                >= self.cooldown_seconds
            ):
                suggestion = ProactiveSuggestion(
                    event_id=f"proactive_{uuid.uuid4().hex}",
                    kind=kind,
                    title="Изменения давно не сохранены в Git",
                    message=(
                        f"{resolved.name}: {len(lines)} изменённых "
                        "файлов. Посмотреть diff и сделать commit?"
                    ),
                    reason=(
                        "Репозиторий остаётся dirty дольше "
                        f"{uncommitted_after_seconds / 60:.0f} мин."
                    ),
                    source_key=(
                        f"repo:{repo_key}:uncommitted:{cycle}"
                    ),
                    importance="normal",
                )
                self._store(suggestion)
                self._last_emitted[kind] = now
                state["commit_notified"] = True
                suggestions.append(suggestion)

        self._set_state(state_key, state)
        return suggestions

    def record_tool_completion(
        self,
        payload: Mapping[str, Any],
    ) -> None:
        if not bool(payload.get("success")):
            return
        if str(payload.get("risk") or "") == "read_only":
            return

        tool_name = str(payload.get("tool_name") or "")
        operation_id = str(payload.get("operation_id") or "")
        session_id = str(payload.get("session_id") or "")
        turn_id = str(payload.get("turn_id") or "")
        if not all(
            (tool_name, operation_id, session_id, turn_id)
        ):
            return
        if tool_name in {
            "execute_plan",
            "start_background_plan",
            "retry_background_plan",
            "cancel_background_plan",
        }:
            return

        self.database.execute(
            """
            INSERT OR IGNORE INTO tool_activity (
                operation_id,
                tool_name,
                session_id,
                turn_id,
                observed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                tool_name,
                session_id,
                turn_id,
                self.clock(),
            ),
        )
        self.database.commit()

    def observe_repeated_actions(
        self,
        *,
        min_repetitions: int = 3,
        lookback_seconds: float = 14 * 24 * 60 * 60,
        max_sequence_length: int = 8,
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        kind = "workflow_suggested"
        if not self._kind_enabled(kind):
            return []

        cutoff = self.clock() - max(0.0, lookback_seconds)
        self.database.execute(
            """
            DELETE FROM tool_activity
            WHERE observed_at < ?
            """,
            (cutoff,),
        )
        self.database.commit()
        rows = self.database.fetchall(
            """
            SELECT tool_name, session_id, turn_id
            FROM tool_activity
            WHERE observed_at >= ?
            ORDER BY observed_at ASC, rowid ASC
            LIMIT 2000
            """,
            (cutoff,),
        )
        turns: dict[tuple[str, str], list[str]] = {}
        for row in rows:
            turn_key = (
                str(row["session_id"]),
                str(row["turn_id"]),
            )
            turns.setdefault(turn_key, []).append(
                str(row["tool_name"])
            )

        patterns: dict[tuple[str, ...], int] = {}
        for tools in turns.values():
            if not 1 <= len(tools) <= max(1, max_sequence_length):
                continue
            pattern = tuple(tools)
            patterns[pattern] = patterns.get(pattern, 0) + 1

        threshold = max(2, int(min_repetitions))
        candidates = sorted(
            (
                (count, pattern)
                for pattern, count in patterns.items()
                if count >= threshold
            ),
            key=lambda item: (-item[0], item[1]),
        )
        now = self.clock()
        for count, pattern in candidates:
            fingerprint = hashlib.sha256(
                "\0".join(pattern).encode("utf-8")
            ).hexdigest()[:20]
            source_key = f"workflow-pattern:{fingerprint}"
            if self._was_emitted(source_key):
                continue
            if (
                now - self._last_emitted.get(kind, 0.0)
                < self.cooldown_seconds
            ):
                return []

            sequence = " → ".join(pattern)
            workflow_name = "Nova workflow " + fingerprint[:6]
            suggestion = ProactiveSuggestion(
                event_id=f"proactive_{uuid.uuid4().hex}",
                kind=kind,
                title="Превратить повторяющиеся действия в workflow?",
                message=(
                    f"Последовательность «{sequence}» повторилась "
                    f"{count} раза."
                ),
                reason=(
                    "Совпала последовательность успешных tool-вызовов "
                    "в разных пользовательских turn; аргументы и "
                    "результаты для анализа не сохранялись."
                ),
                source_key=source_key,
                importance="normal",
                suggested_request=(
                    f"Начни запись workflow с именем «{workflow_name}». "
                    "Я повторю действие ещё раз, после чего остановлю запись."
                ),
                action_label="Начать запись",
            )
            self._store(suggestion)
            self._last_emitted[kind] = now
            return [suggestion]

        return []

    def observe_website_changes(
        self,
        changes: Iterable[Mapping[str, Any]],
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        kind = "website_changed"
        if not self._kind_enabled(kind):
            return []

        now = self.clock()
        suggestions: list[ProactiveSuggestion] = []
        for change in changes:
            watch_id = str(change.get("watch_id") or "")
            revision = int(change.get("revision") or 0)
            url = str(change.get("url") or "")
            label = str(change.get("label") or "").strip() or url
            if not watch_id or revision <= 0 or not url:
                continue

            source_key = (
                f"website:{watch_id}:revision:{revision}"
            )
            if self._was_emitted(source_key):
                continue
            if (
                now - self._last_emitted.get(kind, 0.0)
                < self.cooldown_seconds
            ):
                continue

            suggestion = ProactiveSuggestion(
                event_id=f"proactive_{uuid.uuid4().hex}",
                kind=kind,
                title="Страница изменилась",
                message=f"{label}: обнаружено новое содержимое.",
                reason=(
                    "SHA-256 нормализованного текста отличается от "
                    "предыдущего baseline. Текст страницы не "
                    "передавался модели."
                ),
                source_key=source_key,
                importance="normal",
            )
            self._store(suggestion)
            self._last_emitted[kind] = now
            suggestions.append(suggestion)

        return suggestions

    def observe_backup_statuses(
        self,
        statuses: Iterable[Mapping[str, Any]],
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        now = self.clock()
        suggestions: list[ProactiveSuggestion] = []
        for item in statuses:
            watch_id = str(item.get("watch_id") or "")
            status = str(item.get("status") or "")
            if not watch_id or status not in {
                "healthy",
                "stale",
                "missing",
            }:
                continue

            state_key = f"backup_watch:{watch_id}"
            previous = self._get_state(state_key)
            cycle = int(previous.get("cycle", 0))
            if status == "healthy":
                if previous.get("status") != "healthy":
                    self._set_state(
                        state_key,
                        {"status": "healthy", "cycle": cycle},
                    )
                continue
            if previous.get("status") == status:
                continue

            kind = (
                "backup_stale"
                if status == "stale"
                else "backup_missing"
            )
            if not self._kind_enabled(kind):
                continue
            if (
                now - self._last_emitted.get(kind, 0.0)
                < self.cooldown_seconds
            ):
                continue

            cycle += 1
            label = (
                str(item.get("label") or "").strip()
                or Path(str(item.get("path") or "")).name
                or watch_id
            )
            if status == "stale":
                age_hours = float(item.get("age_seconds") or 0.0) / 3600
                title = "Резервная копия устарела"
                message = (
                    f"{label}: последняя копия создана "
                    f"{age_hours:.1f} ч назад."
                )
                reason = (
                    "Возраст последнего файла превысил настроенный "
                    "max_age_hours."
                )
            else:
                title = "Резервная копия не найдена"
                message = (
                    f"{label}: в отслеживаемом пути нет доступных "
                    "файлов резервной копии."
                )
                reason = (
                    "Путь исчез, пуст или не может быть проверен; "
                    "содержимое файлов Nova не читала."
                )

            suggestion = ProactiveSuggestion(
                event_id=f"proactive_{uuid.uuid4().hex}",
                kind=kind,
                title=title,
                message=message,
                reason=reason,
                source_key=(
                    f"backup:{watch_id}:{status}:{cycle}"
                ),
                importance="high",
            )
            self._store(suggestion)
            self._set_state(
                state_key,
                {"status": status, "cycle": cycle},
            )
            self._last_emitted[kind] = now
            suggestions.append(suggestion)

        return suggestions

    def observe_package_updates(
        self,
        statuses: Iterable[Mapping[str, Any]],
    ) -> list[ProactiveSuggestion]:
        if self._is_quiet_time():
            return []

        kind = "package_update_available"
        if not self._kind_enabled(kind):
            return []

        now = self.clock()
        suggestions: list[ProactiveSuggestion] = []
        for item in statuses:
            if (
                not bool(item.get("update_available"))
                or item.get("error")
            ):
                continue
            package_name = str(item.get("package_name") or "")
            installed = str(item.get("installed_version") or "")
            latest = str(item.get("latest_version") or "")
            if not all((package_name, installed, latest)):
                continue

            source_key = f"package:{package_name}:version:{latest}"
            if self._was_emitted(source_key):
                continue
            if (
                now - self._last_emitted.get(kind, 0.0)
                < self.cooldown_seconds
            ):
                continue

            suggestion = ProactiveSuggestion(
                event_id=f"proactive_{uuid.uuid4().hex}",
                kind=kind,
                title="Доступно обновление Python-пакета",
                message=(
                    f"{package_name}: {installed} → {latest}. "
                    "Показать release notes или обновить?"
                ),
                reason=(
                    "Установленная версия получена из локального "
                    "package metadata, последняя — из фиксированного "
                    "PyPI JSON endpoint. Nova ничего не обновляла."
                ),
                source_key=source_key,
                importance="normal",
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
