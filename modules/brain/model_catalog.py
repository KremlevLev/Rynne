# modules/brain/model_catalog.py
"""
Model Catalog - каталог моделей с capabilities, health monitoring и pinning.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Профиль модели с capabilities и ограничениями."""

    model_id: str
    provider: str
    max_tokens: int
    supports_tools: bool = False
    supports_vision: bool = False
    default_priority: int = 100
    cost_per_1k_tokens: float = 0.0

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.model_id}"


@dataclass(slots=True)
class ModelHealth:
    """Health статус модели."""

    model_id: str
    provider: str
    last_error: str | None = None
    error_count: int = 0
    last_check: datetime | None = None
    is_available: bool = True
    cooldown_until: datetime | None = None
    avg_latency_ms: float = 0.0
    success_rate: float = 1.0

    def mark_success(self, latency_ms: float = 0.0) -> None:
        self.is_available = True
        self.error_count = 0
        self.last_error = None
        self.last_check = datetime.now()
        self.avg_latency_ms = (
            self.avg_latency_ms * 0.7 + latency_ms * 0.3
        ) if self.avg_latency_ms else latency_ms
        self.success_rate = min(1.0, self.success_rate + 0.1)

    def mark_error(self, error: str) -> None:
        self.error_count += 1
        self.last_error = error
        self.last_check = datetime.now()
        self.success_rate = max(0.0, self.success_rate - 0.2)
        if self.error_count >= 3:
            self.is_available = False


class ModelCatalog:
    """
    Каталог моделей с health monitoring и pinning.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ModelProfile] = {}
        self._health: dict[str, ModelHealth] = {}
        self._pinned_model: str | None = None

    def register(
        self,
        model_id: str,
        provider: str,
        *,
        max_tokens: int,
        supports_tools: bool = False,
        supports_vision: bool = False,
        default_priority: int = 100,
        cost_per_1k_tokens: float = 0.0,
    ) -> None:
        """Регистрация модели в каталоге."""
        key = f"{provider}:{model_id}"
        self._profiles[key] = ModelProfile(
            model_id=model_id,
            provider=provider,
            max_tokens=max_tokens,
            supports_tools=supports_tools,
            supports_vision=supports_vision,
            default_priority=default_priority,
            cost_per_1k_tokens=cost_per_1k_tokens,
        )
        if key not in self._health:
            self._health[key] = ModelHealth(
                model_id=model_id,
                provider=provider,
            )

    def get_profile(self, model_id: str) -> ModelProfile | None:
        """Получить профиль модели."""
        return self._profiles.get(model_id)

    def get_health(self, model_id: str) -> ModelHealth | None:
        """Получить health статус модели."""
        return self._health.get(model_id)

    def is_available(self, model_id: str) -> bool:
        """Проверить доступность модели."""
        if model_id in self._health:
            health = self._health[model_id]
            if health.cooldown_until:
                if datetime.now() < health.cooldown_until:
                    return False
                health.cooldown_until = None
                health.is_available = True
            return health.is_available
        return True

    def pin_model(self, model_id: str) -> None:
        """Закрепить модель для принудительного использования."""
        self._pinned_model = model_id

    def get_pinned_model(self) -> str | None:
        """Получить закреплённую модель."""
        return self._pinned_model

    def unpin_model(self) -> None:
        """Снять закрепление модели."""
        self._pinned_model = None

    def get_capabilities(
        self,
        model_id: str,
    ) -> dict[str, Any]:
        """Получить capabilities модели."""
        profile = self._profiles.get(model_id)
        if profile is None:
            return {}
        return {
            "supports_tools": profile.supports_tools,
            "supports_vision": profile.supports_vision,
            "max_tokens": profile.max_tokens,
            "cost_per_1k_tokens": profile.cost_per_1k_tokens,
        }


# Глобальный каталог
_catalog: ModelCatalog | None = None


def get_catalog() -> ModelCatalog:
    """Получить глобальный каталог моделей."""
    global _catalog
    if _catalog is None:
        _catalog = ModelCatalog()
    return _catalog


def init_catalog() -> ModelCatalog:
    """
    Инициализировать каталог базовыми моделями.
    Вызывается при старте приложения.
    """
    catalog = ModelCatalog()

    # Groq uses one strong model for chat and tool calling.
    catalog.register(
        "openai/gpt-oss-120b",
        "groq",
        max_tokens=131072,
        supports_tools=True,
        supports_vision=False,
        default_priority=10,
    )
    catalog.register(
        "qwen/qwen3.6-27b",
        "groq",
        max_tokens=131072,
        supports_tools=True,
        supports_vision=True,
        default_priority=10,
    )

    # Gemini models
    catalog.register(
        "gemini-2.5-flash",
        "gemini",
        max_tokens=1000000,
        supports_tools=True,
        supports_vision=True,
        default_priority=20,
        cost_per_1k_tokens=0.0000125,
    )
    catalog.register(
        "gemini-2.0-flash",
        "gemini",
        max_tokens=1000000,
        supports_tools=True,
        supports_vision=True,
        default_priority=30,
        cost_per_1k_tokens=0.0000125,
    )

    # OpenRouter models
    catalog.register(
        "anthropic/claude-3.5-sonnet",
        "openrouter",
        max_tokens=8192,
        supports_tools=True,
        supports_vision=True,
        default_priority=30,
    )

    _catalog = catalog
    return catalog
