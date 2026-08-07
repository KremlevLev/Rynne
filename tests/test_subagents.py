from __future__ import annotations

import asyncio
from types import SimpleNamespace

from modules.agent import subagents
from modules.agent.subagents import SubagentPool, should_auto_delegate
from modules.brain.model_gateway import KeySlot, ModelGateway
from modules.brain.model_router import ModelCandidate, TaskComplexity


class FakeLLM:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.prompts: list[str] = []

    def provider_health(self):
        return {
            "keys": [
                {"provider": "groq", "available": True, "quota_group": None},
                {"provider": "openrouter", "available": True, "quota_group": None},
                {"provider": "gemini", "available": True, "quota_group": "project-a"},
                {"provider": "gemini", "available": True, "quota_group": "project-a"},
            ]
        }

    async def complete(self, *, candidates, messages, **_kwargs):
        prompt = str(messages[-1]["content"])
        self.prompts.append(prompt)
        reviewer = "Отчёты команды" in prompt
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        candidate = candidates[0]
        return SimpleNamespace(
            provider=candidate.provider,
            model=candidate.model,
            text="Единый проверенный план" if reviewer else "Конкретный вывод специалиста",
        )


def fake_route(_complexity):
    return [
        ModelCandidate(provider="groq", model="text-model"),
        ModelCandidate(provider="openrouter", model="reasoning-model"),
        ModelCandidate(provider="gemini", model="gemini-model"),
    ]


def test_capacity_counts_independent_quota_groups_once(monkeypatch) -> None:
    monkeypatch.setattr(subagents, "build_model_route", fake_route)
    pool = SubagentPool(FakeLLM())
    assert pool.provider_capacity() == {"groq": 1, "openrouter": 1, "gemini": 1}
    assert pool.parallel_capacity() == 3


def test_team_runs_in_parallel_and_preserves_original_intent(monkeypatch) -> None:
    monkeypatch.setattr(subagents, "build_model_route", fake_route)
    llm = FakeLLM()
    pool = SubagentPool(llm)
    goal = "Исправь голос и UI, не проси меня объяснять второй раз"

    result = asyncio.run(pool.run(goal=goal))

    assert result["success"] is True
    assert result["parallel_agents"] == 3
    assert result["synthesis"] == "Единый проверенный план"
    assert llm.max_active == 3
    assert all(goal in prompt for prompt in llm.prompts)


def test_auto_delegation_only_targets_multi_part_complex_work() -> None:
    assert should_auto_delegate(
        "Изучи проект, исправь голос и заодно улучши UI",
        TaskComplexity.COMPLEX_TOOL,
    )
    assert not should_auto_delegate("Открой Chrome", TaskComplexity.BASIC_TOOL)


def test_gateway_prefers_idle_key_for_parallel_request() -> None:
    gateway = ModelGateway()
    busy = KeySlot(provider="groq", index=0, api_key="a", in_flight_requests=1)
    idle = KeySlot(provider="groq", index=1, api_key="b")
    gateway._key_slots["groq"] = [busy, idle]
    gateway._preferred_key_index["groq"] = 0

    assert gateway._ordered_slots("groq")[0] is idle
