"""Локальная память успешных tool-последовательностей Nova.

Это не изменение весов модели. Модуль сохраняет только обезличенный шаблон
цели и имена успешно сработавших инструментов, а затем предлагает похожие
последовательности AgentService как необязательный execution playbook.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger("ExecutionMemory")

DEFAULT_EXECUTION_MEMORY_PATH = Path(
    "data/learning/execution_patterns.json"
)
_STOP_WORDS = {
    "а", "без", "бы", "в", "во", "для", "до", "и", "или", "к",
    "как", "мне", "мой", "моя", "мою", "на", "не", "но", "о", "по",
    "с", "со", "там", "то", "это", "я", "the", "a", "an", "and",
    "for", "in", "of", "on", "to", "with",
}


def goal_terms(text: str) -> tuple[str, ...]:
    normalized = str(text).lower().replace("ё", "е")
    terms = {
        token
        for token in re.findall(r"[a-zа-я0-9]{3,}", normalized)
        if token not in _STOP_WORDS and not token.isdigit()
    }
    return tuple(sorted(terms))


def _goal_fingerprints(text: str) -> tuple[str, ...]:
    """Create stable, one-way term identifiers for private local matching."""
    return tuple(
        sorted(
            hashlib.blake2s(
                term.encode("utf-8"),
                digest_size=12,
            ).hexdigest()
            for term in goal_terms(text)
        )
    )


@dataclass(frozen=True, slots=True)
class ExecutionPlaybook:
    terms: tuple[str, ...]
    tools: tuple[str, ...]
    success_count: int
    updated_at: float
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "terms": list(self.terms),
            "tools": list(self.tools),
            "success_count": self.success_count,
            "updated_at": self.updated_at,
        }


class ExecutionMemory:
    """Bounded JSON store for successful, non-secret execution patterns."""

    def __init__(
        self,
        path: Path | str = DEFAULT_EXECUTION_MEMORY_PATH,
        *,
        max_patterns: int = 200,
    ) -> None:
        self.path = Path(path)
        self.max_patterns = max(10, int(max_patterns))
        self._lock = threading.RLock()

    def _load(self) -> list[ExecutionPlaybook]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Не удалось прочитать execution memory.", exc_info=True)
            return []

        patterns: list[ExecutionPlaybook] = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            terms = tuple(str(value) for value in item.get("terms", []) if value)
            tools = tuple(str(value) for value in item.get("tools", []) if value)
            if not terms or not tools:
                continue
            patterns.append(
                ExecutionPlaybook(
                    terms=terms,
                    tools=tools,
                    success_count=max(1, int(item.get("success_count", 1))),
                    updated_at=float(item.get("updated_at", 0.0)),
                )
            )
        return patterns

    def _save(self, patterns: list[ExecutionPlaybook]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                [pattern.to_dict() for pattern in patterns],
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def remember_success(
        self,
        goal: str,
        tool_results: list[dict[str, Any]],
    ) -> bool:
        terms = _goal_fingerprints(goal)
        tools: list[str] = []
        for item in tool_results:
            result = item.get("result")
            if not isinstance(result, dict) or not bool(result.get("success")):
                return False
            name = str(item.get("name") or "").strip()
            if name and (not tools or tools[-1] != name):
                tools.append(name)

        if not terms or not tools:
            return False

        now = time.time()
        signature = (terms, tuple(tools))
        with self._lock:
            patterns = self._load()
            updated: list[ExecutionPlaybook] = []
            matched = False
            for pattern in patterns:
                if (pattern.terms, pattern.tools) == signature:
                    updated.append(
                        ExecutionPlaybook(
                            terms=pattern.terms,
                            tools=pattern.tools,
                            success_count=pattern.success_count + 1,
                            updated_at=now,
                        )
                    )
                    matched = True
                else:
                    updated.append(pattern)
            if not matched:
                updated.append(
                    ExecutionPlaybook(
                        terms=terms,
                        tools=tuple(tools),
                        success_count=1,
                        updated_at=now,
                    )
                )
            updated.sort(
                key=lambda item: (item.success_count, item.updated_at),
                reverse=True,
            )
            self._save(updated[: self.max_patterns])
        return True

    def find(
        self,
        goal: str,
        available_tools: set[str],
        *,
        limit: int = 3,
    ) -> list[ExecutionPlaybook]:
        requested = set(_goal_fingerprints(goal))
        if not requested:
            return []

        matches: list[ExecutionPlaybook] = []
        with self._lock:
            patterns = self._load()
        for pattern in patterns:
            if not set(pattern.tools).issubset(available_tools):
                continue
            known = set(pattern.terms)
            overlap = len(requested & known)
            if not overlap:
                continue
            score = overlap / len(requested | known)
            score += min(0.2, 0.03 * (pattern.success_count - 1))
            matches.append(
                ExecutionPlaybook(
                    terms=pattern.terms,
                    tools=pattern.tools,
                    success_count=pattern.success_count,
                    updated_at=pattern.updated_at,
                    score=score,
                )
            )
        matches.sort(
            key=lambda item: (item.score, item.success_count, item.updated_at),
            reverse=True,
        )
        return matches[: max(0, int(limit))]

    def prompt_for(self, goal: str, available_tools: set[str]) -> str:
        matches = self.find(goal, available_tools)
        if not matches:
            return ""
        lines = [
            "LEARNED EXECUTION PLAYBOOKS:",
            "Ниже только подсказки из прошлых успешных запусков. Проверь их ",
            "применимость к текущему состоянию и не пропускай verification.",
        ]
        for index, match in enumerate(matches, 1):
            lines.append(
                f"{index}. {' -> '.join(match.tools)} "
                f"(успехов: {match.success_count})"
            )
        return "\n".join(lines)
