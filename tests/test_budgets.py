# tests/test_budgets.py
from __future__ import annotations

from modules.tools.budgets import (
    AgentBudget,
    BudgetManager,
    BudgetState,
)
from modules.application.agent import AgentService


def test_budget_starts_not_exhausted() -> None:
    state = BudgetState()

    exhausted, reason = state.is_exhausted(
        AgentBudget()
    )

    assert not exhausted
    assert reason is None


def test_model_call_limit_works() -> None:
    budget = AgentBudget(max_logical_model_calls=2)
    state = BudgetState()

    state.record_model_call()
    state.record_model_call()

    exhausted, reason = state.is_exhausted(budget)

    assert exhausted
    assert reason is not None
    assert "логических модельных вызовов" in reason


def test_tool_call_limit_works() -> None:
    budget = AgentBudget(max_tool_calls=3)
    state = BudgetState()

    for _ in range(3):
        state.record_tool_call("tool_a")

    exhausted, reason = state.is_exhausted(budget)

    assert exhausted
    assert "инструментов" in reason


def test_time_limit_works() -> None:
    import time

    budget = AgentBudget(
        max_wall_time_seconds=0.01
    )
    state = BudgetState()

    time.sleep(0.02)

    exhausted, reason = state.is_exhausted(budget)

    assert exhausted
    assert "времени" in reason


def test_tool_repeat_detection() -> None:
    budget = AgentBudget(
        max_same_tool_repeats=2
    )
    state = BudgetState()

    state.record_tool_call("tool_a")
    state.record_tool_call("tool_a")

    assert state.is_tool_repeated(
        "tool_a",
        budget,
    )

    assert not state.is_tool_repeated(
        "tool_b",
        budget,
    )


def test_budget_manager_creates_and_removes_state() -> None:
    manager = BudgetManager()

    state = manager.create_state("turn-1")

    assert state is not None

    assert (
        manager.get_state("turn-1") is state
    )

    manager.remove_state("turn-1")

    assert (
        manager.get_state("turn-1") is None
    )


def test_budget_manager_records_calls() -> None:
    manager = BudgetManager()

    manager.create_state("turn-1")

    manager.record_model_call("turn-1")
    manager.record_tool_call(
        "turn-1",
        "tool_a",
    )

    state = manager.get_state("turn-1")

    assert state is not None
    assert state.model_calls_used == 1
    assert state.tool_calls_used == 1


def test_agent_budget_scales_with_independent_provider_lanes() -> None:
    service = AgentService.__new__(AgentService)
    service.default_budget = AgentBudget()
    service.subagent_pool = type(
        "CapacityPool",
        (),
        {"parallel_capacity": lambda self: 4},
    )()

    budget = service._budget_for_available_capacity()

    assert budget.max_logical_model_calls == 11
    assert budget.max_tool_calls == 32
    assert budget.max_tokens == 64_000
