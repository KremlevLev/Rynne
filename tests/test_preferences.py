# tests/test_preferences.py
from __future__ import annotations

from modules.application.preferences import (
    PreferencesManager,
)
from modules.input_hub.models import (
    AssistantProfile,
    InputMode,
    ModelSelectionMode,
)


def test_default_preferences() -> None:
    manager = PreferencesManager()

    snapshot = manager.snapshot()

    assert snapshot.input_mode in {
        InputMode.WAKE_WORD,
        InputMode.SLEEP,
    }

    assert (
        snapshot.assistant_profile
        == AssistantProfile.ASSISTANT
    )
    assert (
        snapshot.model_mode
        == ModelSelectionMode.AUTO
    )
    assert snapshot.cloud_enabled
    assert snapshot.history_enabled
    assert not snapshot.proactive_vision_enabled
    assert snapshot.ui_performance_mode == "aura"


def test_ui_performance_mode_is_persisted_and_validated(
    monkeypatch,
    tmp_path,
) -> None:
    from modules.application import preferences as preferences_module

    monkeypatch.setattr(
        preferences_module,
        "PREFERENCES_PATH",
        tmp_path / "preferences.json",
    )
    manager = PreferencesManager()
    assert manager.set_ui_performance_mode("console").ui_performance_mode == "console"
    assert PreferencesManager().snapshot().ui_performance_mode == "console"

    try:
        manager.set_ui_performance_mode("turbo")
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown UI mode must be rejected")


def test_privacy_mode_disables_cloud_and_history() -> None:
    manager = PreferencesManager()
    manager.set_proactive_vision_enabled(True)

    snapshot = manager.set_input_mode(
        InputMode.PRIVACY
    )

    assert not snapshot.cloud_enabled
    assert not snapshot.history_enabled
    assert not snapshot.proactive_vision_enabled


def test_proactive_vision_requires_cloud_and_is_opt_in() -> None:
    manager = PreferencesManager()

    enabled = manager.set_proactive_vision_enabled(
        True
    )
    assert enabled.proactive_vision_enabled

    disabled_cloud = manager.set_cloud_enabled(False)
    assert not disabled_cloud.proactive_vision_enabled

    try:
        manager.set_proactive_vision_enabled(True)
    except ValueError as exc:
        assert "vision" in str(exc)
    else:
        raise AssertionError(
            "Proactive vision was enabled without cloud."
        )


def test_private_profile_uses_local_model() -> None:
    manager = PreferencesManager()

    snapshot = manager.set_assistant_profile(
        AssistantProfile.PRIVATE_LOCAL
    )

    assert (
        snapshot.model_mode
        == ModelSelectionMode.LOCAL_ONLY
    )
    assert not snapshot.cloud_enabled


def test_pinned_model_requires_name() -> None:
    manager = PreferencesManager()

    try:
        manager.set_model_mode(
            ModelSelectionMode.PINNED
        )
    except ValueError as exc:
        assert "указать модель" in str(exc)
    else:
        raise AssertionError(
            "PINNED без модели не был отклонён."
        )


def test_pinned_model() -> None:
    manager = PreferencesManager()

    snapshot = manager.set_model_mode(
        ModelSelectionMode.PINNED,
        selected_model="test/model",
    )

    assert (
        snapshot.model_mode
        == ModelSelectionMode.PINNED
    )
    assert (
        snapshot.selected_model
        == "test/model"
    )
def test_wake_word_default_when_configured(
    monkeypatch,
    tmp_path,
) -> None:
    model_directory = (
        tmp_path / "vosk-model"
    )
    model_directory.mkdir()

    monkeypatch.setenv(
        "NOVA_WAKE_WORD_ENABLED",
        "true",
    )
    monkeypatch.setenv(
        "NOVA_VOSK_MODEL",
        str(model_directory),
    )

    manager = PreferencesManager()

    assert (
        manager.snapshot().input_mode
        == InputMode.WAKE_WORD
    )


def test_continuous_listening_requires_explicit_opt_in(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "NOVA_CONTINUOUS_LISTENING",
        "true",
    )
    monkeypatch.setenv(
        "NOVA_WAKE_WORD_ENABLED",
        "false",
    )

    manager = PreferencesManager()

    assert (
        manager.snapshot().input_mode
        == InputMode.CONTINUOUS
    )
