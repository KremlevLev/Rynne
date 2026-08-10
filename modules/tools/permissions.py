# modules/tools/permissions.py
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

from modules.tools.policy import (
    PolicyContext,
    PolicyDecision,
    evaluate_policy,
    format_confirmation_message,
)


logger = logging.getLogger("Permissions")


class PermissionMode(StrEnum):
    """How often Nova asks before executing a tool."""

    FULL_ACCESS = "full_access"
    RISKY_ONLY = "risky_only"
    ALWAYS_ASK = "always_ask"

    @classmethod
    def parse(cls, value: str | None) -> "PermissionMode":
        normalized = str(value or "").strip().lower()
        aliases = {
            "full": cls.FULL_ACCESS,
            "autonomous": cls.FULL_ACCESS,
            "balanced": cls.RISKY_ONLY,
            "safe": cls.RISKY_ONLY,
            "strict": cls.ALWAYS_ASK,
            "always": cls.ALWAYS_ASK,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return cls(normalized)
        except ValueError:
            return cls.RISKY_ONLY


@dataclass(slots=True)
class PermissionRequest:
    operation_id: str
    policy_context: PolicyContext
    decision: PolicyDecision
    message: str

    created_at: float = field(
        default_factory=time.time
    )
    expires_at: float = 0.0

    resolved: bool = False
    granted: bool = False
    resolution: str | None = None

    def is_expired(self) -> bool:
        return (
            self.expires_at > 0
            and time.time() > self.expires_at
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "operation_id": self.operation_id,
            "tool_name": (
                self.policy_context.tool_name
            ),
            "category": (
                self.policy_context.tool_category.value
            ),
            "risk": (
                self.policy_context.risk.value
            ),
            "arguments": (
                self.policy_context.arguments
            ),
            "source": self.policy_context.source,
            "expected_window": (
                self.policy_context.expected_window
            ),
            "working_directory": (
                str(
                    self.policy_context.working_directory
                )
                if (
                    self.policy_context.working_directory
                    is not None
                )
                else None
            ),
            "decision": self.decision.value,
            "message": self.message,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "resolved": self.resolved,
            "granted": self.granted,
            "resolution": self.resolution,
        }
        for key in (
            "telegram_remote",
            "telegram_remote_chat_id",
            "telegram_remote_user_id",
        ):
            if key in self.policy_context.metadata:
                payload[key] = self.policy_context.metadata[key]
        return payload


class PermissionManager:
    """
    Централизованный менеджер разрешений Nova.

    Опасные действия ожидают решения пользователя. Если решение
    не получено до timeout, действие запрещается.
    """

    def __init__(
        self,
        *,
        event_sink: Callable[[str, dict[str, Any]], Any] | None = None,
        mode: PermissionMode | str | None = None,
    ) -> None:
        self._pending: dict[
            str,
            PermissionRequest,
        ] = {}

        self._resolution_events: dict[
            str,
            asyncio.Event,
        ] = {}

        self._lock = threading.RLock()
        self._event_sink = event_sink
        self.mode = PermissionMode.parse(
            mode if mode is not None else os.getenv("NOVA_PERMISSION_MODE")
        )

    def _decision(self, policy_context: PolicyContext) -> PolicyDecision:
        """Apply the user-selected approval cadence over the hard policy."""
        decision = evaluate_policy(policy_context)
        if decision == PolicyDecision.DENY:
            return decision
        if self.mode == PermissionMode.FULL_ACCESS:
            return PolicyDecision.ALLOW
        if self.mode == PermissionMode.ALWAYS_ASK:
            if policy_context.risk.value == "destructive":
                return PolicyDecision.REQUIRE_STRONG_CONFIRMATION
            return PolicyDecision.REQUIRE_CONFIRMATION
        return decision

    def set_event_sink(
        self,
        event_sink: Callable[[str, dict[str, Any]], Any] | None,
    ) -> None:
        self._event_sink = event_sink

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_sink is None:
            return
        try:
            self._event_sink(event_type, payload)
        except Exception:
            logger.exception("Не удалось отправить событие разрешения: %s.", event_type)

    def request(
        self,
        policy_context: PolicyContext,
        *,
        expires_after_seconds: float = 60.0,
    ) -> PermissionRequest:
        decision = self._decision(policy_context)

        request = PermissionRequest(
            operation_id=(
                policy_context.operation_id
            ),
            policy_context=policy_context,
            decision=decision,
            message=format_confirmation_message(
                policy_context
            ),
            expires_at=(
                time.time()
                + expires_after_seconds
                if decision
                in {
                    PolicyDecision.REQUIRE_CONFIRMATION,
                    PolicyDecision.REQUIRE_STRONG_CONFIRMATION,
                }
                else 0.0
            ),
        )

        with self._lock:
            self._pending[
                request.operation_id
            ] = request

            self._resolution_events[
                request.operation_id
            ] = asyncio.Event()

        logger.info(
            (
                "Запрос разрешения: operation_id=%s "
                "tool=%s decision=%s"
            ),
            request.operation_id,
            policy_context.tool_name,
            decision.value,
        )

        if request.decision in {
            PolicyDecision.REQUIRE_CONFIRMATION,
            PolicyDecision.REQUIRE_STRONG_CONFIRMATION,
        }:
            self._emit("approval_requested", request.to_dict())

        return request

    def check(
        self,
        policy_context: PolicyContext,
    ) -> tuple[bool, str | None]:
        decision = self._decision(policy_context)

        if decision == PolicyDecision.DENY:
            return (
                False,
                (
                    f"Инструмент "
                    f"'{policy_context.tool_name}' "
                    "запрещен политикой безопасности."
                ),
            )

        if decision in {
            PolicyDecision.REQUIRE_CONFIRMATION,
            PolicyDecision.REQUIRE_STRONG_CONFIRMATION,
        }:
            return False, None

        return True, None

    def confirm(
        self,
        operation_id: str,
    ) -> bool:
        with self._lock:
            request = self._pending.get(
                operation_id
            )

            if request is None:
                logger.warning(
                    "Запрос %s не найден.",
                    operation_id,
                )
                return False

            if request.is_expired():
                request.resolved = True
                request.granted = False
                request.resolution = "expired"
                self._set_resolution_event(
                    operation_id
                )
                return False

            if request.resolved:
                return False

            request.resolved = True
            request.granted = True
            request.resolution = "confirmed"

            self._set_resolution_event(
                operation_id
            )

        logger.info(
            "Разрешено: operation_id=%s tool=%s",
            operation_id,
            request.policy_context.tool_name,
        )

        return True

    def deny(
        self,
        operation_id: str,
        *,
        resolution: str = "denied",
    ) -> bool:
        with self._lock:
            request = self._pending.get(
                operation_id
            )

            if request is None:
                return False

            if request.resolved:
                return False

            request.resolved = True
            request.granted = False
            request.resolution = resolution

            self._set_resolution_event(
                operation_id
            )

        logger.info(
            "Запрещено: operation_id=%s tool=%s",
            operation_id,
            request.policy_context.tool_name,
        )

        return True

    def _set_resolution_event(
        self,
        operation_id: str,
    ) -> None:
        event = self._resolution_events.get(
            operation_id
        )

        if event is not None:
            event.set()

    async def wait_for_confirmation(
        self,
        policy_context: PolicyContext,
        *,
        timeout_seconds: float = 60.0,
    ) -> bool:
        request = self.request(
            policy_context,
            expires_after_seconds=(
                timeout_seconds
            ),
        )

        if request.decision in {
            PolicyDecision.ALLOW,
            PolicyDecision.ALLOW_WITH_WARNING,
        }:
            self._remove_request(
                request.operation_id
            )
            return True

        if request.decision == PolicyDecision.DENY:
            self._remove_request(
                request.operation_id
            )
            return False

        with self._lock:
            event = self._resolution_events[
                request.operation_id
            ]

        try:
            await asyncio.wait_for(
                event.wait(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            self.deny(
                request.operation_id,
                resolution="timeout",
            )

        with self._lock:
            resolved_request = self._pending.get(
                request.operation_id
            )

            granted = bool(
                resolved_request
                and resolved_request.resolved
                and resolved_request.granted
            )

        self._remove_request(
            request.operation_id
        )

        return granted

    def _remove_request(
        self,
        operation_id: str,
    ) -> None:
        with self._lock:
            self._pending.pop(
                operation_id,
                None,
            )
            self._resolution_events.pop(
                operation_id,
                None,
            )

    def pending_requests(
        self,
    ) -> list[dict[str, Any]]:
        """
        Возвращает безопасную копию ожидающих запросов для UI.
        """
        expired_ids: list[str] = []

        with self._lock:
            requests = list(
                self._pending.values()
            )

            for request in requests:
                if (
                    request.is_expired()
                    and not request.resolved
                ):
                    expired_ids.append(
                        request.operation_id
                    )

        for operation_id in expired_ids:
            self.deny(
                operation_id,
                resolution="expired",
            )

        with self._lock:
            return [
                request.to_dict()
                for request in self._pending.values()
                if not request.resolved
            ]

    def get_request(
        self,
        operation_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            request = self._pending.get(
                operation_id
            )

            if request is None:
                return None

            return request.to_dict()
