# modules/tools/budgets.py
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field


logger = logging.getLogger("Budgets")


@dataclass(slots=True)
class AgentBudget:
    """
    Бюджет одного пользовательского запроса.

    После исчерпания любого лимита агент должен остановиться
    и сформировать итог по уже выполненным инструментам.
    """

    # Логические вызовы модели: первичный выбор, recovery и продолжение
    # многошаговой цепочки по фактическим результатам инструментов.
    max_logical_model_calls: int = 4

    # Попытки провайдера на один логический вызов
    max_provider_attempts_per_call: int = 4

    # Общее количество попыток провайдера
    max_total_provider_attempts: int = 8

    # Перепланировки
    max_replans: int = 1

    # Вызовы инструментов
    max_tool_calls: int = 10

    # Время выполнения
    max_wall_time_seconds: float = 180.0

    # Повторы одного инструмента
    max_same_tool_repeats: int = 1

    # Размер наблюдений (символы)
    max_observation_characters: int = 4000

    # Для будущего использования.
    max_tokens: int = 0
    max_cost: float = 0.0


@dataclass(slots=True)
class BudgetState:
    """
    Текущее состояние бюджета для одного запроса.
    """

    # Счётчики по новой схеме
    logical_model_calls: int = 0
    provider_attempts: int = 0
    tool_calls: int = 0
    replans: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    observation_characters: int = 0

    started_at: float = field(
        default_factory=time.monotonic
    )

    tool_call_signatures: dict[str, int] = field(
        default_factory=dict
    )

    def elapsed_seconds(self) -> float:
        return (
            time.monotonic() - self.started_at
        )

    def record_logical_model_call(self) -> None:
        self.logical_model_calls += 1

    def record_provider_attempt(self) -> None:
        self.provider_attempts += 1

    def record_tool_call(
        self,
        signature: str,
    ) -> None:
        self.tool_calls += 1
        self.tool_call_signatures[signature] = (
            self.tool_call_signatures.get(
                signature,
                0
            )
            + 1
        )

    def record_replan(self) -> None:
        self.replans += 1

    def record_prompt_tokens(
        self,
        tokens: int,
    ) -> None:
        self.prompt_tokens += tokens

    def record_completion_tokens(
        self,
        tokens: int,
    ) -> None:
        self.completion_tokens += tokens

    def record_observation_characters(
        self,
        chars: int,
    ) -> None:
        self.observation_characters += chars

    def is_exhausted(
        self,
        budget: AgentBudget,
    ) -> tuple[bool, str | None]:
        if (
            self.logical_model_calls
            >= budget.max_logical_model_calls
        ):
            return (
                True,
                (
                    f"Достигнут лимит логических модельных вызовов: "
                    f"{self.logical_model_calls}/"
                    f"{budget.max_logical_model_calls}"
                ),
            )

        if (
            self.provider_attempts
            >= budget.max_total_provider_attempts
        ):
            return (
                True,
                (
                    f"Достигнут лимит попыток провайдера: "
                    f"{self.provider_attempts}/"
                    f"{budget.max_total_provider_attempts}"
                ),
            )

        if (
            self.tool_calls
            >= budget.max_tool_calls
        ):
            return (
                True,
                (
                    f"Достигнут лимит инструментов: "
                    f"{self.tool_calls}/"
                    f"{budget.max_tool_calls}"
                ),
            )

        if (
            self.replans
            >= budget.max_replans
        ):
            return (
                True,
                (
                    f"Достигнут лимит перепланировок: "
                    f"{self.replans}/"
                    f"{budget.max_replans}"
                ),
            )

        elapsed = self.elapsed_seconds()

        if (
            elapsed
            >= budget.max_wall_time_seconds
        ):
            return (
                True,
                (
                    f"Достигнут лимит времени: "
                    f"{elapsed:.0f}/"
                    f"{budget.max_wall_time_seconds:.0f} сек."
                ),
            )

        if (
            self.observation_characters
            >= budget.max_observation_characters
        ):
            return (
                True,
                (
                    f"Достигнут лимит символов наблюдений: "
                    f"{self.observation_characters}/"
                    f"{budget.max_observation_characters}"
                ),
            )

        return (False, None)

    def is_tool_repeated(
        self,
        signature: str,
        budget: AgentBudget,
    ) -> bool:
        current_count = (
            self.tool_call_signatures.get(
                signature,
                0
            )
        )

        return (
            current_count
            >= budget.max_same_tool_repeats
        )

    # Обратная совместимость
    def record_model_call(self) -> None:
        """Алиас для record_logical_model_call."""
        self.record_logical_model_call()

    @property
    def model_calls_used(self) -> int:
        return self.logical_model_calls

    @property
    def tool_calls_used(self) -> int:
        return self.tool_calls


class BudgetManager:
    """
    Управляет бюджетами для каждого пользовательского запроса.
    """

    def __init__(self) -> None:
        self._states: dict[
            str,
            BudgetState,
        ] = {}
        self._lock = threading.RLock()
        self.default_budget = AgentBudget()

    def create_state(
        self,
        turn_id: str,
        *,
        budget: AgentBudget | None = None,
    ) -> BudgetState:
        with self._lock:
            state = BudgetState()
            self._states[turn_id] = state

        return state

    def get_state(
        self,
        turn_id: str,
    ) -> BudgetState | None:
        with self._lock:
            return self._states.get(turn_id)

    def remove_state(
        self,
        turn_id: str,
    ) -> None:
        with self._lock:
            self._states.pop(turn_id, None)

    def record_logical_model_call(
        self,
        turn_id: str,
    ) -> None:
        state = self.get_state(turn_id)

        if state is not None:
            state.record_logical_model_call()

    def record_provider_attempt(
        self,
        turn_id: str,
    ) -> None:
        state = self.get_state(turn_id)

        if state is not None:
            state.record_provider_attempt()

    def record_model_call(
        self,
        turn_id: str,
    ) -> None:
        state = self.get_state(turn_id)

        if state is not None:
            state.record_logical_model_call()

    def record_tool_call(
        self,
        turn_id: str,
        signature: str,
    ) -> None:
        state = self.get_state(turn_id)

        if state is not None:
            state.record_tool_call(signature)

    def is_exhausted(
        self,
        turn_id: str,
        *,
        budget: AgentBudget | None = None,
    ) -> tuple[bool, str | None]:
        state = self.get_state(turn_id)

        if state is None:
            return (False, None)

        return state.is_exhausted(
            budget or self.default_budget
        )

    def is_tool_repeated(
        self,
        turn_id: str,
        signature: str,
        *,
        budget: AgentBudget | None = None,
    ) -> bool:
        state = self.get_state(turn_id)

        if state is None:
            return False

        return state.is_tool_repeated(
            signature,
            budget or self.default_budget,
        )
