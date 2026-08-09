# modules/routing/decision.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExecutionStrategy(StrEnum):
    DIRECT = "direct"
    SKILL = "skill"
    WORKFLOW = "workflow"
    PLAN = "plan"
    CHAT = "chat"
    CLARIFY = "clarify"
    DENY = "deny"


class IntentKind(StrEnum):
    CHAT = "chat"

    APPLICATION_OPEN = "application_open"
    APPLICATION_CLOSE = "application_close"
    APPLICATION_WRITE = "application_write"
    APPLICATION_BATCH = "application_batch"

    SYSTEM_TIME = "system_time"
    SYSTEM_VOLUME = "system_volume"
    SYSTEM_WINDOWS = "system_windows"

    FILE_OPERATION = "file_operation"
    DEVELOPMENT = "development"
    WEB = "web"
    MESSAGING = "messaging"
    MEMORY = "memory"
    REMINDER = "reminder"

    MODEL_SELECTION = "model_selection"
    MODE_SELECTION = "mode_selection"

    VISION = "vision"
    UNKNOWN_ACTION = "unknown_action"


@dataclass(slots=True)
class ExecutionDecision:
    strategy: ExecutionStrategy
    intent: IntentKind

    required_tools: set[str] = field(
        default_factory=set
    )

    selected_skill: str | None = None
    workflow_name: str | None = None

    arguments: dict[str, Any] = field(
        default_factory=dict
    )

    needs_model: bool = False
    needs_tools: bool = False
    needs_clarification: bool = False

    clarification_question: str | None = None
    denial_reason: str | None = None

    expected_model_calls: int = 0
    expected_tool_calls: int = 0

    confidence: float = 1.0
    reason: str = ""

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @classmethod
    def chat(
        cls,
        *,
        reason: str = "",
    ) -> "ExecutionDecision":
        return cls(
            strategy=ExecutionStrategy.CHAT,
            intent=IntentKind.CHAT,
            needs_model=True,
            needs_tools=False,
            expected_model_calls=1,
            expected_tool_calls=0,
            reason=reason,
        )

    @classmethod
    def clarify(
        cls,
        question: str,
        *,
        intent: IntentKind = (
            IntentKind.UNKNOWN_ACTION
        ),
        reason: str = "",
    ) -> "ExecutionDecision":
        return cls(
            strategy=ExecutionStrategy.CLARIFY,
            intent=intent,
            needs_model=False,
            needs_tools=False,
            needs_clarification=True,
            clarification_question=question,
            expected_model_calls=0,
            expected_tool_calls=0,
            reason=reason,
        )

    @classmethod
    def deny(
        cls,
        reason: str,
        *,
        intent: IntentKind = (
            IntentKind.UNKNOWN_ACTION
        ),
    ) -> "ExecutionDecision":
        return cls(
            strategy=ExecutionStrategy.DENY,
            intent=intent,
            denial_reason=reason,
            needs_model=False,
            needs_tools=False,
            expected_model_calls=0,
            expected_tool_calls=0,
            reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "intent": self.intent.value,
            "required_tools": sorted(
                self.required_tools
            ),
            "selected_skill": (
                self.selected_skill
            ),
            "workflow_name": self.workflow_name,
            "arguments": self.arguments,
            "needs_model": self.needs_model,
            "needs_tools": self.needs_tools,
            "needs_clarification": (
                self.needs_clarification
            ),
            "clarification_question": (
                self.clarification_question
            ),
            "denial_reason": (
                self.denial_reason
            ),
            "expected_model_calls": (
                self.expected_model_calls
            ),
            "expected_tool_calls": (
                self.expected_tool_calls
            ),
            "confidence": self.confidence,
            "reason": self.reason,
            "metadata": self.metadata,
        }
