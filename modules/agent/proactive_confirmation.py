from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from modules.agent.proactive import ProactiveSuggestion


AFFIRMATIVE_PHRASES = frozenset({
    "да",
    "давай",
    "подтверждаю",
    "выполняй",
    "сделай",
    "ок",
    "окей",
    "хорошо",
})
NEGATIVE_PHRASES = frozenset({
    "нет",
    "не надо",
    "не сейчас",
    "отмена",
    "отмени",
})


@dataclass(frozen=True, slots=True)
class PendingProactiveAction:
    event_id: str
    request: str
    context_key: str
    title: str
    action_label: str
    expires_at: float


class ProactiveConfirmationManager:
    """Keeps one short-lived proactive action awaiting explicit consent."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 45.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ttl_seconds = max(10.0, ttl_seconds)
        self.clock = clock
        self._pending: PendingProactiveAction | None = None

    def arm(
        self,
        suggestion: ProactiveSuggestion,
    ) -> PendingProactiveAction | None:
        request = str(suggestion.suggested_request or "").strip()
        if not request:
            self._pending = None
            return None
        self._pending = PendingProactiveAction(
            event_id=suggestion.event_id,
            request=request,
            context_key=suggestion.source_key,
            title=suggestion.title,
            action_label=(
                suggestion.action_label or "Выполнить"
            ),
            expires_at=self.clock() + self.ttl_seconds,
        )
        return self._pending

    def pending(self) -> PendingProactiveAction | None:
        item = self._pending
        if item is not None and item.expires_at <= self.clock():
            self._pending = None
            return None
        return item

    def confirm(
        self,
        event_id: str | None = None,
    ) -> PendingProactiveAction | None:
        item = self.pending()
        if item is None:
            return None
        if event_id and event_id != item.event_id:
            return None
        self._pending = None
        return item

    def reject(self) -> PendingProactiveAction | None:
        item = self.pending()
        self._pending = None
        return item

    @staticmethod
    def classify_voice(text: str) -> str | None:
        normalized = re.sub(
            r"[^a-zа-яё0-9 ]+",
            " ",
            str(text).casefold(),
        )
        normalized = " ".join(normalized.split())
        if normalized in AFFIRMATIVE_PHRASES:
            return "accepted"
        if normalized in NEGATIVE_PHRASES:
            return "dismissed"
        return None

