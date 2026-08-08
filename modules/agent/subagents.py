from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable

from modules.brain.llm import NovaLLM
from modules.brain.model_router import (
    ModelCandidate,
    TaskComplexity,
    build_model_route,
)


logger = logging.getLogger("SubagentPool")

MAX_SUBAGENTS = 6


@dataclass(slots=True)
class SubagentResult:
    agent_id: str
    role: str
    task: str
    provider: str = ""
    model: str = ""
    answer: str = ""
    success: bool = False
    error: str = ""


def should_auto_delegate(
    text: str,
    complexity: TaskComplexity,
) -> bool:
    """Use a team only when parallel perspectives are likely to repay latency."""
    normalized = str(text).lower()
    if complexity == TaskComplexity.ULTRA:
        return True
    if complexity != TaskComplexity.COMPLEX_TOOL:
        return False
    markers = (
        " и заодно ",
        " плюс ",
        "одновременно",
        "параллел",
        "весь проект",
        "полный аудит",
        "архитектур",
        "миграц",
        "рефактор",
        "несколько",
    )
    action_verbs = re.findall(
        r"\b(?:добавь|сделай|исправь|проверь|изучи|перепиши|улучши|найди)\w*\b",
        normalized,
    )
    return (
        len(normalized) >= 320
        or len(action_verbs) >= 2
        or any(marker in normalized for marker in markers)
    )


class SubagentPool:
    """Parallel, read-only model workers that preserve and clarify user intent.

    Workers never execute tools or mutate the workspace. Their consensus is fed
    back to the primary agent, which remains the only authority that performs
    actions and therefore keeps Nova's normal permission and verification path.
    """

    def __init__(
        self,
        llm: NovaLLM,
        *,
        event_handler: Callable[[str, dict[str, Any]], Any] | None = None,
        max_agents: int = MAX_SUBAGENTS,
    ) -> None:
        self.llm = llm
        self.event_handler = event_handler
        self.max_agents = min(MAX_SUBAGENTS, max(1, int(max_agents)))

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_handler is None:
            return
        try:
            self.event_handler(event_type, payload)
        except Exception:
            logger.debug("Subagent event delivery failed.", exc_info=True)

    def provider_capacity(self) -> dict[str, int]:
        health = self.llm.provider_health()
        keys = health.get("keys", [])
        capacity: dict[str, int] = {}
        gemini_groups: set[str] = set()
        for item in keys if isinstance(keys, list) else []:
            if not isinstance(item, dict) or not item.get("available"):
                continue
            provider = str(item.get("provider") or "")
            if not provider:
                continue
            if provider == "gemini" and item.get("quota_group"):
                gemini_groups.add(str(item["quota_group"]))
                continue
            capacity[provider] = capacity.get(provider, 0) + 1
        if gemini_groups:
            capacity["gemini"] = capacity.get("gemini", 0) + len(gemini_groups)
        return capacity

    def parallel_capacity(self) -> int:
        return min(self.max_agents, sum(self.provider_capacity().values()))

    def capacity_snapshot(self) -> dict[str, Any]:
        providers = self.provider_capacity()
        parallel = min(self.max_agents, sum(providers.values()))
        return {
            "provider_capacity": providers,
            "parallel_capacity": parallel,
            "critic_enabled": parallel >= 2,
            "adaptive_budget": parallel > 1,
        }

    @staticmethod
    def default_subtasks(goal: str, capacity: int = 3) -> list[dict[str, str]]:
        del goal
        tasks = [
            {
                "role": "intent_guardian",
                "task": (
                    "Зафиксируй точный intent пользователя: обязательные результаты, "
                    "ограничения, контекст продолжения и что нельзя потерять. Не проси "
                    "повторять уже сказанное; разрешай несущественные пробелы разумными допущениями."
                ),
            },
            {
                "role": "execution_architect",
                "task": (
                    "Предложи самый прямой исполнимый план, нужные инструменты и порядок "
                    "проверки результата. Найди независимые части и зависимости."
                ),
            },
            {
                "role": "failure_hunter",
                "task": (
                    "Найди вероятные причины провала, конфликтующие действия и конкретные "
                    "проверки, после которых можно честно считать задачу выполненной."
                ),
            },
        ]
        if capacity >= 4:
            tasks.append(
                {
                    "role": "evidence_researcher",
                    "task": (
                        "Проверь фактические предпосылки, существующие возможности и контекст. "
                        "Отдели подтверждённое от предположений и перечисли недостающие доказательства."
                    ),
                }
            )
        if capacity >= 5:
            tasks.append(
                {
                    "role": "independent_solver",
                    "task": (
                        "Независимо реши задачу другим способом и сравни его по скорости, "
                        "надёжности и полноте с очевидным подходом."
                    ),
                }
            )
        if capacity >= 6:
            tasks.append(
                {
                    "role": "adversarial_critic",
                    "task": (
                        "Попытайся опровергнуть предлагаемый план: найди скрытые пробелы, "
                        "ложные успехи и проверки, которые могут дать неверный результат."
                    ),
                }
            )
        return tasks

    @staticmethod
    def _normalize_subtasks(
        subtasks: list[dict[str, Any]] | list[str] | None,
        goal: str,
        capacity: int = 3,
    ) -> list[dict[str, str]]:
        if not subtasks:
            return SubagentPool.default_subtasks(goal, capacity)
        normalized: list[dict[str, str]] = []
        for index, item in enumerate(subtasks):
            if isinstance(item, str):
                task = item.strip()
                role = f"specialist_{index + 1}"
            elif isinstance(item, dict):
                task = str(item.get("task") or "").strip()
                role = str(item.get("role") or f"specialist_{index + 1}").strip()
            else:
                continue
            if task:
                normalized.append({"role": role[:80], "task": task[:2000]})
        return normalized or SubagentPool.default_subtasks(goal, capacity)

    @staticmethod
    def _route_for_provider(
        complexity: TaskComplexity,
        provider: str,
    ) -> list[ModelCandidate]:
        route = build_model_route(complexity)
        preferred = [item for item in route if item.provider == provider]
        fallback = [item for item in route if item.provider != provider]
        return preferred + fallback

    @staticmethod
    def _complexity_for_role(role: str) -> TaskComplexity:
        normalized = role.lower()
        if any(marker in normalized for marker in ("architect", "архитектор", "review")):
            return TaskComplexity.ULTRA
        return TaskComplexity.COMPLEX_TOOL

    async def _run_worker(
        self,
        *,
        team_id: str,
        goal: str,
        context: str,
        role: str,
        task: str,
        provider: str,
    ) -> SubagentResult:
        agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        result = SubagentResult(agent_id=agent_id, role=role, task=task)
        self._publish(
            "subagent_started",
            {"team_id": team_id, "agent_id": agent_id, "role": role, "task": task},
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Ты временный субагент Nova. Работай только аналитически: не заявляй, "
                    "что запускал инструменты или изменял систему. Сохраняй исходный intent "
                    "дословно, не подменяй цель удобной задачей. Дай конкретный результат "
                    "главному агенту, который реально выполнит действия."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"ИСХОДНАЯ ЦЕЛЬ ПОЛЬЗОВАТЕЛЯ:\n{goal}\n\n"
                    f"ТВОЯ РОЛЬ: {role}\nТВОЯ ПОДЗАДАЧА:\n{task}\n\n"
                    f"ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ:\n{context or 'нет'}"
                ),
            },
        ]
        try:
            response = await self.llm.complete(
                candidates=self._route_for_provider(
                    self._complexity_for_role(role),
                    provider,
                ),
                messages=messages,
                tools=None,
                allow_tools=False,
            )
            result.provider = response.provider
            result.model = response.model
            result.answer = response.text.strip()[:6000]
            result.success = bool(result.answer)
            if not result.success:
                result.error = "Пустой ответ субагента."
        except Exception as exc:
            result.error = str(exc)
            logger.warning("Subagent %s failed: %s", role, exc)
        self._publish("subagent_completed", {"team_id": team_id, **asdict(result)})
        return result

    async def _review(
        self,
        goal: str,
        results: list[SubagentResult],
    ) -> str:
        successful = [item for item in results if item.success]
        if not successful:
            return ""
        evidence = "\n\n".join(
            f"[{item.role} | {item.provider}:{item.model}]\n{item.answer}"
            for item in successful
        )
        route = build_model_route(TaskComplexity.ULTRA) or build_model_route(
            TaskComplexity.COMPLEX_TOOL
        )
        try:
            response = await self.llm.complete(
                candidates=route,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты reviewer команды Nova. Сведи выводы без потери intent. "
                            "Удали противоречия и болтовню. Верни главному агенту: точную цель, "
                            "исполняемый порядок действий, проверки и важные ограничения. "
                            "Не утверждай, что действия уже выполнены."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Цель:\n{goal}\n\nОтчёты команды:\n{evidence}",
                    },
                ],
                tools=None,
                allow_tools=False,
            )
            return response.text.strip()[:8000]
        except Exception as exc:
            logger.warning("Subagent reviewer failed: %s", exc)
            return evidence

    async def _critic(self, goal: str, synthesis: str) -> dict[str, Any]:
        if not synthesis:
            return {"passed": False, "critique": "Reviewer не создал результат."}
        self._publish("subagent_critic_started", {"goal": goal})
        route = build_model_route(TaskComplexity.ULTRA) or build_model_route(
            TaskComplexity.COMPLEX_TOOL
        )
        try:
            response = await self.llm.complete(
                candidates=route,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты независимый critic Nova. Проверь, сохраняет ли синтез точный "
                            "intent, исполним ли план, есть ли проверка результата и не заявлены "
                            "ли невыполненные действия. Первая строка строго PASS или REVISE. "
                            "Далее кратко перечисли только существенные замечания."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Цель:\n{goal}\n\nСинтез:\n{synthesis}",
                    },
                ],
                tools=None,
                allow_tools=False,
            )
            critique = response.text.strip()[:5000]
            first_line = critique.upper().splitlines()[0].strip() if critique else ""
            # Only an explicit REVISE triggers the bounded repair pass. Models that
            # ignore the requested envelope must not erase a valid reviewer result.
            passed = first_line != "REVISE"
        except Exception as exc:
            critique = f"Critic недоступен: {exc}"
            passed = True
        result = {"passed": passed, "critique": critique}
        self._publish("subagent_critic_completed", result)
        return result

    async def _revise(self, goal: str, synthesis: str, critique: str) -> str:
        route = build_model_route(TaskComplexity.ULTRA) or build_model_route(
            TaskComplexity.COMPLEX_TOOL
        )
        try:
            response = await self.llm.complete(
                candidates=route,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты manager Nova. Исправь синтез по замечаниям critic за один проход. "
                            "Не добавляй неподтверждённых действий и не меняй цель пользователя."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Цель:\n{goal}\n\nСинтез:\n{synthesis}\n\n"
                            f"Замечания critic:\n{critique}"
                        ),
                    },
                ],
                tools=None,
                allow_tools=False,
            )
            return response.text.strip()[:8000] or synthesis
        except Exception:
            return synthesis

    async def run(
        self,
        *,
        goal: str,
        subtasks: list[dict[str, Any]] | list[str] | None = None,
        context: str = "",
        max_agents: int | None = None,
    ) -> dict[str, Any]:
        goal = str(goal).strip()
        if not goal:
            return {"success": False, "error": "Пустая цель для команды субагентов."}
        capacity = self.parallel_capacity()
        tasks = self._normalize_subtasks(subtasks, goal, capacity)
        requested = self.max_agents if max_agents is None else max(1, int(max_agents))
        worker_count = min(len(tasks), requested, capacity, MAX_SUBAGENTS)
        if worker_count <= 0:
            return {
                "success": False,
                "error": "Нет доступных API-ключей для субагентов.",
                "capacity": 0,
            }
        capacities = self.provider_capacity()
        lanes = [provider for provider, count in capacities.items() for _ in range(count)]
        team_id = f"team_{uuid.uuid4().hex[:10]}"
        selected = tasks[:worker_count]
        self._publish(
            "subagent_team_started",
            {
                "team_id": team_id,
                "goal": goal,
                "agents": worker_count,
                "capacity": capacity,
            },
        )
        results = await asyncio.gather(
            *(
                self._run_worker(
                    team_id=team_id,
                    goal=goal,
                    context=context,
                    role=item["role"],
                    task=item["task"],
                    provider=lanes[index % len(lanes)],
                )
                for index, item in enumerate(selected)
            )
        )
        synthesis = await self._review(goal, list(results))
        critic = {"passed": True, "critique": "Critic отключён: нужна вторая независимая линия."}
        review_iterations = 1
        if capacity >= 2 and synthesis:
            critic = await self._critic(goal, synthesis)
            if not critic["passed"]:
                synthesis = await self._revise(goal, synthesis, str(critic["critique"]))
                review_iterations = 2
        payload = {
            "success": bool(synthesis),
            "team_id": team_id,
            "goal": goal,
            "parallel_agents": worker_count,
            "available_capacity": capacity,
            "provider_capacity": capacities,
            "resource_profile": self.capacity_snapshot(),
            "results": [asdict(item) for item in results],
            "synthesis": synthesis,
            "critic": critic,
            "critic_passed": bool(critic["passed"]),
            "review_iterations": review_iterations,
        }
        self._publish("subagent_team_completed", payload)
        return payload

    async def delegate_subagents(
        self,
        goal: str,
        subtasks: list[dict[str, Any]] | list[str] | None = None,
        context: str = "",
        max_agents: int | None = None,
    ) -> dict[str, Any]:
        return await self.run(
            goal=goal,
            subtasks=subtasks,
            context=context,
            max_agents=max_agents,
        )


__all__ = ["SubagentPool", "SubagentResult", "should_auto_delegate"]
