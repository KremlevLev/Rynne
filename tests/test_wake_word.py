# tests/test_wake_word.py
from __future__ import annotations

import builtins
from pathlib import Path

from modules.input_hub.wake_word import (
    WakeWordConfig,
    WakeWordDetector,
    contains_wake_word,
    normalize_wake_text,
    strip_wake_prefix,
)


def test_normalize_wake_text() -> None:
    assert (
        normalize_wake_text(
            "  НОВА,   Открой  "
        )
        == "нова, открой"
    )


def test_contains_wake_word() -> None:
    assert contains_wake_word(
        "Нова открой блокнот"
    )

    assert contains_wake_word(
        "Эй, Нова!"
    )

    assert contains_wake_word(
        "ново"
    )


def test_does_not_match_part_of_word() -> None:
    assert not contains_wake_word(
        "инновация"
    )


def test_strip_simple_wake_prefix() -> None:
    assert (
        strip_wake_prefix(
            "Нова, открой блокнот"
        )
        == "открой блокнот"
    )


def test_strip_hey_nova_prefix() -> None:
    assert (
        strip_wake_prefix(
            "Эй Нова, скажи время"
        )
        == "скажи время"
    )


def test_strip_listen_nova_prefix() -> None:
    assert (
        strip_wake_prefix(
            "Слушай, Нова, открой браузер"
        )
        == "открой браузер"
    )


def test_wake_only_returns_empty_command() -> None:
    assert strip_wake_prefix(
        "Нова"
    ) == ""


def test_text_without_wake_prefix_is_unchanged() -> None:
    assert (
        strip_wake_prefix(
            "Открой блокнот"
        )
        == "Открой блокнот"
    )


def test_detector_unavailable_without_model() -> None:
    config = WakeWordConfig(
        enabled=True,
        wake_word="нова",
        model_path=Path(
            "missing-vosk-model"
        ),
        model_configured=True,
    )

    detector = WakeWordDetector(config)

    assert not detector.available

def test_detector_available_with_model_directory(
    tmp_path,
) -> None:
    model_directory = (
        tmp_path / "vosk-model"
    )
    model_directory.mkdir()

    config = WakeWordConfig(
        enabled=True,
        wake_word="нова",
        model_path=model_directory,
        model_configured=True,
    )

    detector = WakeWordDetector(config)

    assert detector.available


def test_environment_config_auto_enables_discovered_model(
    tmp_path,
    monkeypatch,
) -> None:
    model_directory = tmp_path / "vosk-model"
    model_directory.mkdir()
    monkeypatch.setenv("NOVA_VOSK_MODEL", str(model_directory))
    monkeypatch.delenv("NOVA_WAKE_WORD_ENABLED", raising=False)

    config = WakeWordConfig.from_environment()

    assert config.available
    assert config.model_path == model_directory.resolve()


def test_explicit_environment_switch_can_disable_wake_word(
    tmp_path,
    monkeypatch,
) -> None:
    model_directory = tmp_path / "vosk-model"
    model_directory.mkdir()
    monkeypatch.setenv("NOVA_VOSK_MODEL", str(model_directory))
    monkeypatch.setenv("NOVA_WAKE_WORD_ENABLED", "false")

    assert not WakeWordConfig.from_environment().available


def test_detector_caches_fatal_vosk_initialization_error(
    tmp_path,
    monkeypatch,
) -> None:
    model_directory = tmp_path / "vosk-model"
    model_directory.mkdir()
    detector = WakeWordDetector(
        WakeWordConfig(
            enabled=True,
            wake_word="нова",
            model_path=model_directory,
            model_configured=True,
        )
    )
    original_import = builtins.__import__
    attempts = 0

    def fail_vosk_import(name, *args, **kwargs):
        nonlocal attempts
        if name == "vosk":
            attempts += 1
            raise ImportError("broken vosk runtime")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(
        builtins,
        "__import__",
        fail_vosk_import,
    )

    first = detector.wait_for_command()
    second = detector.wait_for_command()

    assert not first.success
    assert not second.success
    assert attempts == 1
