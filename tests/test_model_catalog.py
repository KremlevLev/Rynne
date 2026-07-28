# tests/test_model_catalog.py
from __future__ import annotations

from modules.brain.model_catalog import (
    ModelProfile,
    ModelHealth,
    ModelCatalog,
    init_catalog,
)


def test_model_profile_creation() -> None:
    profile = ModelProfile(
        model_id="test-model",
        provider="test-provider",
        max_tokens=8192,
        supports_tools=True,
        supports_vision=False,
        default_priority=10,
    )

    assert profile.model_id == "test-model"
    assert profile.provider == "test-provider"
    assert profile.max_tokens == 8192
    assert profile.supports_tools is True
    assert profile.supports_vision is False
    assert profile.identity == "test-provider:test-model"


def test_model_health_mark_success() -> None:
    health = ModelHealth(
        model_id="test-model",
        provider="test-provider",
    )

    health.mark_success(100.0)

    assert health.is_available is True
    assert health.error_count == 0
    assert health.last_error is None
    assert health.avg_latency_ms == 100.0
    # success_rate начинается с 1.0 и увеличивается
    assert health.success_rate >= 1.0


def test_model_health_mark_error() -> None:
    health = ModelHealth(
        model_id="test-model",
        provider="test-provider",
    )

    health.mark_error("API Error")
    health.mark_error("Timeout")
    health.mark_error("Rate limit")

    assert health.error_count == 3
    assert health.is_available is False
    # success_rate уменьшается при ошибках: 1.0 - 0.2 - 0.2 - 0.2 = 0.4
    assert abs(health.success_rate - 0.4) < 0.01


def test_model_catalog_register_and_get() -> None:
    catalog = ModelCatalog()

    catalog.register(
        "test-model",
        "test-provider",
        max_tokens=8192,
        supports_tools=True,
    )

    profile = catalog.get_profile("test-provider:test-model")
    assert profile is not None
    assert profile.model_id == "test-model"
    assert profile.supports_tools is True


def test_model_catalog_availability() -> None:
    catalog = ModelCatalog()
    catalog.register("test-model", "test-provider", max_tokens=8192)

    assert catalog.is_available("test-provider:test-model") is True

    health = catalog.get_health("test-provider:test-model")
    if health:
        health.mark_error("Error")
        health.mark_error("Error")
        health.mark_error("Error")

    assert catalog.is_available("test-provider:test-model") is False


def test_model_catalog_pinning() -> None:
    catalog = ModelCatalog()
    catalog.register("model-a", "provider-a", max_tokens=8192)
    catalog.register("model-b", "provider-b", max_tokens=8192)

    assert catalog.get_pinned_model() is None

    catalog.pin_model("provider-a:model-a")

    assert catalog.get_pinned_model() == "provider-a:model-a"

    catalog.unpin_model()

    assert catalog.get_pinned_model() is None


def test_model_catalog_capabilities() -> None:
    catalog = ModelCatalog()
    catalog.register(
        "test-model",
        "test-provider",
        max_tokens=8192,
        supports_tools=True,
        supports_vision=True,
        cost_per_1k_tokens=0.01,
    )

    caps = catalog.get_capabilities("test-provider:test-model")

    assert caps["supports_tools"] is True
    assert caps["supports_vision"] is True
    assert caps["max_tokens"] == 8192
    assert caps["cost_per_1k_tokens"] == 0.01


def test_init_catalog_creates_basic_models() -> None:
    catalog = init_catalog()

    assert catalog.get_profile("groq:openai/gpt-oss-120b") is not None
    assert catalog.get_profile("groq:llama-3.1-8b-instant") is None
    assert catalog.get_profile("gemini:gemini-2.5-flash") is not None
    assert catalog.get_profile("gemini:gemini-2.0-flash") is not None
    assert catalog.get_profile("openrouter:anthropic/claude-3.5-sonnet") is not None
