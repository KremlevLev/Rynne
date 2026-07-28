# modules/agent/reasoning.py
"""Reasoning Loop / ReAct Pattern implementation.

Iterative reasoning loop с self-reflection и dynamic replanning.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from modules.application.reporting import (
    build_assistant_response_from_tools,
)
from modules.domain.results import AssistantResponse
from modules.routing.intent import DeterministicIntentRouter
from modules.tools.base import ToolContext
from modules.tools.runtime import ToolRegistry, ToolRunner


logger = logging.getLogger("ReasoningLoop")


class ReasoningPhase(StrEnum):
    """Фазы reasoning loop."""
    THOUGHT = "thought"
    ACTION = "action"
    OBSERVATION = "observation"
    REFLECTION = "reflection"


@dataclass(slots=True)
class ReasoningStep:
    """Отдельный шаг reasoning loop."""
    phase: ReasoningPhase
    content: str
    tool_calls: list[dict[str, Any]] = field(
        default_factory=list
    )
    tool_results: list[dict[str, Any]] = field(
        default_factory=list
    )
    confidence: float = 0.0
    should_continue: bool = True


@dataclass(slots=True)
class ReasoningState:
    """Состояние reasoning loop."""
    turn_id: str
    session_id: str
    original_request: str
    
    steps: list[ReasoningStep] = field(
        default_factory=list
    )
    
    current_iteration: int = 0
    max_iterations: int = 5
    
    partial_results: list[dict[str, Any]] = field(
        default_factory=list
    )
    
    confidence_threshold: float = 0.8
    
    goal_achieved: bool = False
    final_answer: str | None = None


class ReasoningLoop:
    """
    Iterative reasoning loop для агента.
    
    Реализует паттерн ReAct:
    1. Thought - модель анализирует текущую ситуацию
    2. Action - модель выбирает действия (tool calls)
    3. Observation - результаты выполнения действий
    4. Reflection - оценка результатов и корректировка плана
    """
    
    def __init__(
        self,
        *,
        llm,
        registry: ToolRegistry,
        runner: ToolRunner,
        intent_router: DeterministicIntentRouter | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.runner = runner
        self.intent_router = intent_router
    
    async def run(
        self,
        state: ReasoningState,
        *,
        tools: list[dict[str, Any]] | None = None,
        has_image: bool = False,
    ) -> AssistantResponse:
        """
        Запускает reasoning loop.
        
        Возвращает AssistantResponse с результатом выполнения.
        """
        all_tool_results: list[dict[str, Any]] = []
        
        # Получаем схемы инструментов для передачи модели
        tool_schemas = self.registry.schemas() if self.registry else None
        
        while state.current_iteration < state.max_iterations:
            state.current_iteration += 1
            
            logger.info(
                "Reasoning iteration %s/%s",
                state.current_iteration,
                state.max_iterations,
            )
            
            # Фаза THOUGHT: анализ текущей ситуации
            thought_step = await self._think(state, tools=tool_schemas)
            
            if not thought_step.should_continue:
                break
            
            # Фаза ACTION: выполнение инструментов
            action_results = await self._act(
                thought_step,
                state,
                tools=tools,
            )
            
            all_tool_results.extend(action_results)
            
            # Обновляем состояние частичными результатами
            state.partial_results.extend(action_results)
            
            # Фаза REFLECTION: оценка результатов
            reflection = await self._reflect(thought_step, state)
            
            # Проверяем, достигнута ли цель
            if state.goal_achieved or reflection.confidence >= state.confidence_threshold:
                state.final_answer = reflection.content
                break
        
        # Формируем финальный отчёт
        return build_assistant_response_from_tools(
            all_tool_results,
            budget_exhausted=not state.goal_achieved,
        )
    
    async def run_parallel(
        self,
        state: ReasoningState,
        *,
        tools: list[dict[str, Any]] | None = None,
        has_image: bool = False,
    ) -> AssistantResponse:
        """
        Запускает reasoning loop с параллельным выполнением инструментов.
        
        Все инструменты в рамках одной итерации выполняются параллельно.
        """
        all_tool_results: list[dict[str, Any]] = []
        
        tool_schemas = self.registry.schemas() if self.registry else None
        
        while state.current_iteration < state.max_iterations:
            state.current_iteration += 1
            
            logger.info(
                "Reasoning iteration %s/%s (parallel)",
                state.current_iteration,
                state.max_iterations,
            )
            
            # Фаза THOUGHT: анализ текущей ситуации
            thought_step = await self._think(state, tools=tool_schemas)
            
            if not thought_step.should_continue:
                break
            
            # Фаза ACTION: параллельное выполнение инструментов
            action_results = await self._act_parallel(
                thought_step,
                state,
            )
            
            all_tool_results.extend(action_results)
            state.partial_results.extend(action_results)
            
            # Фаза REFLECTION: оценка результатов
            reflection = await self._reflect(thought_step, state)
            
            if state.goal_achieved or reflection.confidence >= state.confidence_threshold:
                state.final_answer = reflection.content
                break
        
        return build_assistant_response_from_tools(
            all_tool_results,
            budget_exhausted=not state.goal_achieved,
        )
    
    async def _think(
        self,
        state: ReasoningState,
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ReasoningStep:
        """
        Фаза THOUGHT: модель анализирует ситуацию и формирует план.
        """
        from core.config import SYSTEM_PROMPT
        from modules.brain.model_router import (
            ModelCandidate,
        )
        
        # Формируем контекст с историей reasoning
        thinking_context = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        
        # Добавляем информацию о предыдущих шагах
        for step in state.steps:
            thinking_context.append({
                "role": "assistant",
                "content": f"[{step.phase.value.upper()}] {step.content}",
            })
        
        # Добавляем текущий запрос
        thinking_context.append({
            "role": "user",
            "content": (
                "Итерация reasoning loop. "
                "Проанализируй текущую ситуацию и определи следующие шаги.\n"
                f"Исходный запрос: {state.original_request}\n"
                f"Текущая итерация: {state.current_iteration}/{state.max_iterations}"
            ),
        })
        
        # Добавляем результаты, если они есть
        if state.partial_results:
            thinking_context.append({
                "role": "user",
                "content": (
                    "Выполненные действия:\n"
                    + self._format_results(state.partial_results)
                ),
            })
        
        try:
            candidates = [
                ModelCandidate(
                    provider="groq",
                    model="openai/gpt-oss-120b",
                    supports_tools=True,
                    supports_vision=False,
                ),
            ]
            
            response = await self.llm.complete(
                candidates=candidates,
                messages=thinking_context,
                tools=tools,
                allow_tools=True,
            )
            
            # Извлекаем tool calls из ответа (native + XML)
            from modules.brain.tool_calls import (
                deduplicate_tool_calls,
                extract_xml_tool_calls,
            )
            
            native_tool_calls = response.tool_calls
            xml_tool_calls = extract_xml_tool_calls(
                response.text,
                self.registry.names,
            )
            
            all_tool_calls = deduplicate_tool_calls(
                native_tool_calls + xml_tool_calls
            )
            
            step = ReasoningStep(
                phase=ReasoningPhase.THOUGHT,
                content=response.text,
                tool_calls=all_tool_calls,
                confidence=0.5,
            )
            
            state.steps.append(step)
            return step
            
        except Exception as exc:
            logger.warning("Thinking phase failed: %s", exc)
            return ReasoningStep(
                phase=ReasoningPhase.THOUGHT,
                content=f"Ошибка анализа: {exc}",
                should_continue=False,
            )
    
    async def _act(
        self,
        thought_step: ReasoningStep,
        state: ReasoningState,
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Фаза ACTION: выполнение выбранных инструментов (последовательно).
        """
        tool_calls = thought_step.tool_calls
        
        if not tool_calls:
            thought_step.should_continue = False
            return []
        
        results: list[dict[str, Any]] = []
        
        for tool_call in tool_calls:
            try:
                context = ToolContext.create(
                    session_id=state.session_id,
                    turn_id=state.turn_id,
                    source="reasoning_loop",
                    metadata={
                        "reasoning_iteration": state.current_iteration,
                        "reasoning_phase": "action",
                    },
                )
                
                result = await self.runner.execute(
                    tool_call,
                    context=context,
                )
                
                results.append({
                    "name": tool_call.get("function", {}).get("name", "unknown"),
                    "arguments": tool_call.get("function", {}).get("arguments", {}),
                    "result": result.to_dict(),
                })
                
            except Exception as exc:
                logger.warning(
                    "Tool execution failed in reasoning: %s",
                    exc,
                )
                results.append({
                    "name": tool_call.get("function", {}).get("name", "unknown"),
                    "error": str(exc),
                })
        
        action_step = ReasoningStep(
            phase=ReasoningPhase.ACTION,
            content=f"Выполнено {len(results)} инструментов",
            tool_calls=tool_calls,
            tool_results=results,
        )
        
        state.steps.append(action_step)
        return results
    
    async def _act_parallel(
        self,
        thought_step: ReasoningStep,
        state: ReasoningState,
    ) -> list[dict[str, Any]]:
        """
        Фаза ACTION: параллельное выполнение инструментов.
        """
        tool_calls = thought_step.tool_calls
        
        if not tool_calls:
            thought_step.should_continue = False
            return []
        
        async def execute_single(tool_call: dict[str, Any]) -> dict[str, Any]:
            try:
                context = ToolContext.create(
                    session_id=state.session_id,
                    turn_id=state.turn_id,
                    source="reasoning_loop_parallel",
                    metadata={
                        "reasoning_iteration": state.current_iteration,
                        "reasoning_phase": "action_parallel",
                    },
                )
                
                result = await self.runner.execute(
                    tool_call,
                    context=context,
                )
                
                return {
                    "name": tool_call.get("function", {}).get("name", "unknown"),
                    "arguments": tool_call.get("function", {}).get("arguments", {}),
                    "result": result.to_dict(),
                }
                
            except Exception as exc:
                logger.warning(
                    "Tool execution failed in parallel reasoning: %s",
                    exc,
                )
                return {
                    "name": tool_call.get("function", {}).get("name", "unknown"),
                    "error": str(exc),
                }
        
        results = await asyncio.gather(*[
            execute_single(tc) for tc in tool_calls
        ])
        
        action_step = ReasoningStep(
            phase=ReasoningPhase.ACTION,
            content=f"Выполнено {len(results)} инструментов (параллельно)",
            tool_calls=tool_calls,
            tool_results=list(results),
        )
        
        state.steps.append(action_step)
        return list(results)
    
    async def _reflect(
        self,
        action_step: ReasoningStep,
        state: ReasoningState,
    ) -> ReasoningStep:
        """
        Фаза REFLECTION: оценка результатов и определение, нужно ли продолжать.
        """
        successful = sum(
            1 for r in action_step.tool_results
            if r.get("result", {}).get("success", False)
        )
        
        total = len(action_step.tool_results)
        
        if total == 0:
            state.goal_achieved = True
            return ReasoningStep(
                phase=ReasoningPhase.REFLECTION,
                content="Цель достигнута без необходимости дополнительных действий.",
                confidence=0.9,
            )
        
        confidence = successful / total if total > 0 else 0.0
        
        if confidence >= state.confidence_threshold:
            state.goal_achieved = True
        
        reflection_step = ReasoningStep(
            phase=ReasoningPhase.REFLECTION,
            content=(
                f"Результаты: {successful}/{total} успешно. "
                f"Уверенность: {confidence:.2%}"
            ),
            confidence=confidence,
        )
        
        state.steps.append(reflection_step)
        return reflection_step
    
    @staticmethod
    def _format_results(results: list[dict[str, Any]]) -> str:
        """Форматирует результаты для передачи в контекст."""
        lines = []
        
        for i, result in enumerate(results, 1):
            status = "✓" if result.get("result", {}).get("success") else "✗"
            name = result.get("name", "unknown")
            message = result.get("result", {}).get("message", "")
            
            lines.append(f"{i}. {status} {name}: {message}")
        
        return "\n".join(lines)
