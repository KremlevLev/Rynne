# tests/test_wake_word.py
from __future__ import annotations

import builtins
from pathlib import Path

from modules.input_hub.wake_word import (
    WakeWordConfig,
    WakeWordDetector,
    contains_wake_word,
    normalize_wake_text,
    should_trigger_wake,
    strip_wake_prefix,
    _abort_input_stream,
    _continuation_rms_threshold,
)


def test_normalize_wake_text() -> None:
    assert (
        normalize_wake_text(
            "  РИН,   Открой  "
        )
        == "рин, открой"
    )


def test_contains_wake_word() -> None:
    assert contains_wake_word(
        "Рин открой блокнот"
    )

    assert contains_wake_word(
        "Эй, Рин!"
    )


def test_repeated_and_latin_wake_words_are_not_commands() -> None:
    assert strip_wake_prefix("Рин, Рин, Рин") == ""
    assert strip_wake_prefix("Rynne.") == ""
    assert strip_wake_prefix("Ринни, открой браузер") == "открой браузер"
    assert strip_wake_prefix("Райне, привет") == "привет"

    assert contains_wake_word(
        "ринн"
    )
    assert contains_wake_word("ринни")
    assert contains_wake_word("райне")


def test_does_not_match_part_of_word() -> None:
    assert not contains_wake_word(
        "ринопластика"
    )
    assert not contains_wake_word("это новая база в майнкрафте")
    assert not contains_wake_word("в ролике сказали Рин в середине фразы")


def test_plain_rynne_partial_waits_for_word_completion() -> None:
    assert not should_trigger_wake("рин", is_final=False)
    assert should_trigger_wake("рин", is_final=True)
    assert not should_trigger_wake("рин открой", is_final=False)
    assert should_trigger_wake("рин открой", is_final=True)
    assert should_trigger_wake("эй рин", is_final=False)
    assert not should_trigger_wake("новая", is_final=True)


def test_strip_simple_wake_prefix() -> None:
    assert (
        strip_wake_prefix(
            "Рин, открой блокнот"
        )
        == "открой блокнот"
    )


def test_strip_hey_rynne_prefix() -> None:
    assert (
        strip_wake_prefix(
            "Эй Рин, скажи время"
        )
        == "скажи время"
    )


def test_strip_listen_rynne_prefix() -> None:
    assert (
        strip_wake_prefix(
            "Слушай, Рин, открой браузер"
        )
        == "открой браузер"
    )


def test_wake_only_returns_empty_command() -> None:
    assert strip_wake_prefix(
        "Рин"
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
        wake_word="рин",
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
        wake_word="рин",
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


def test_environment_uses_rynne_wake_word_by_default(monkeypatch) -> None:
    monkeypatch.delenv("RYNNE_WAKE_WORD", raising=False)
    monkeypatch.delenv("NOVA_WAKE_WORD", raising=False)

    assert WakeWordConfig.from_environment().wake_word == "рин"


def test_environment_migrates_legacy_nova_wake_word(monkeypatch) -> None:
    monkeypatch.delenv("RYNNE_WAKE_WORD", raising=False)
    monkeypatch.setenv("NOVA_WAKE_WORD", "Нова")

    assert WakeWordConfig.from_environment().wake_word == "рин"


def test_explicit_environment_switch_can_disable_wake_word(
    tmp_path,
    monkeypatch,
) -> None:
    model_directory = tmp_path / "vosk-model"
    model_directory.mkdir()
    monkeypatch.setenv("NOVA_VOSK_MODEL", str(model_directory))
    monkeypatch.setenv("NOVA_WAKE_WORD_ENABLED", "false")

    assert not WakeWordConfig.from_environment().available


def test_wake_stream_uses_abort_instead_of_waiting_for_buffer_drain() -> None:
    class Stream:
        aborted = False

        def abort(self) -> None:
            self.aborted = True

    stream = Stream()

    assert _abort_input_stream(stream)
    assert stream.aborted


def test_wake_silence_threshold_stays_above_measured_noise() -> None:
    config = WakeWordConfig(
        enabled=True,
        wake_word="рин",
        model_path=Path("model"),
        minimum_rms_threshold=0.003,
    )

    threshold = _continuation_rms_threshold(
        config,
        noise_floor=0.01,
        detection_threshold=0.012,
    )

    assert threshold > 0.01


def test_detector_caches_fatal_vosk_initialization_error(
    tmp_path,
    monkeypatch,
) -> None:
    model_directory = tmp_path / "vosk-model"
    model_directory.mkdir()
    detector = WakeWordDetector(
        WakeWordConfig(
            enabled=True,
            wake_word="рин",
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
