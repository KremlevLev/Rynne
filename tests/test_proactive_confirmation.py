from __future__ import annotations

from modules.agent.proactive import ProactiveSuggestion
from modules.agent.proactive_confirmation import ProactiveConfirmationManager


def make_suggestion() -> ProactiveSuggestion:
    return ProactiveSuggestion(
        event_id="proactive_demo",
        kind="proactive_visual_help",
        title="Вижу ошибку",
        message="Могу помочь.",
        reason="Ошибка на экране.",
        source_key="visual:fingerprint",
        suggested_request="Исправь ошибку",
        action_label="Исправить",
    )


def test_voice_confirmation_phrases_are_deliberately_narrow() -> None:
    manager = ProactiveConfirmationManager()
    for phrase in ("да", "давай", "подтверждаю", "выполняй", "окей"):
        assert manager.classify_voice(phrase) == "accepted"
    for phrase in ("нет", "не сейчас", "отмена"):
        assert manager.classify_voice(phrase) == "dismissed"
    assert manager.classify_voice("да, но сначала объясни") is None


def test_pending_confirmation_is_one_shot() -> None:
    manager = ProactiveConfirmationManager()
    pending = manager.arm(make_suggestion())

    assert pending is not None
    assert manager.confirm("another_event") is None
    assert manager.confirm("proactive_demo") == pending
    assert manager.confirm() is None


def test_pending_confirmation_expires() -> None:
    now = [100.0]
    manager = ProactiveConfirmationManager(
        ttl_seconds=10,
        clock=lambda: now[0],
    )
    manager.arm(make_suggestion())
    now[0] = 111.0

    assert manager.pending() is None


def test_suggestion_without_action_does_not_arm_voice_confirmation() -> None:
    manager = ProactiveConfirmationManager()
    suggestion = make_suggestion()
    suggestion = ProactiveSuggestion(
        event_id=suggestion.event_id,
        kind=suggestion.kind,
        title=suggestion.title,
        message=suggestion.message,
        reason=suggestion.reason,
        source_key=suggestion.source_key,
    )

    assert manager.arm(suggestion) is None
