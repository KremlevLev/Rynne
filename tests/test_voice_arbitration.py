from __future__ import annotations

from pathlib import Path

from modules.audio.stt import VoiceListener
from modules.input_hub.voice_owner import get_voice_owner_lock
from modules.input_hub.wake_word import WakeCapture, WakeWordDetector


def test_regular_stt_does_not_open_stream_while_wake_detector_owns_mic(
    monkeypatch,
) -> None:
    lock = get_voice_owner_lock()
    blocker = "test:wake"
    assert lock.acquire(blocker, allow_reentrant=False)
    listener = VoiceListener.__new__(VoiceListener)
    listener.last_error = None
    opened = False

    def fake_listen(_should_abort) -> str:
        nonlocal opened
        opened = True
        return "unexpected"

    monkeypatch.setattr(listener, "_listen_owned", fake_listen)
    try:
        assert listener.listen() == ""
        assert not opened
        assert listener.last_error is None
    finally:
        lock.release(blocker)


def test_wake_detector_does_not_open_stream_while_regular_stt_owns_mic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    lock = get_voice_owner_lock()
    blocker = "test:continuous"
    assert lock.acquire(blocker, allow_reentrant=False)
    detector = WakeWordDetector.__new__(WakeWordDetector)
    opened = False

    def fake_capture(_should_abort) -> WakeCapture:
        nonlocal opened
        opened = True
        return WakeCapture(detected=True, audio_path=tmp_path / "wake.wav")

    monkeypatch.setattr(detector, "_wait_for_command_owned", fake_capture)
    try:
        result = detector.wait_for_command()
        assert not result.success
        assert "переключается" in result.error
        assert not opened
    finally:
        lock.release(blocker)


def test_microphone_lease_is_released_after_recorder_failure(monkeypatch) -> None:
    listener = VoiceListener.__new__(VoiceListener)
    listener.last_error = None

    def fail(_should_abort) -> str:
        raise RuntimeError("recorder failed")

    monkeypatch.setattr(listener, "_listen_owned", fail)
    lock = get_voice_owner_lock()
    assert lock.is_free

    try:
        listener.listen()
    except RuntimeError:
        pass
    else:
        raise AssertionError("Recorder failure was swallowed")

    assert lock.is_free


def test_voice_activity_reports_normalized_live_level() -> None:
    events: list[tuple[str, float]] = []
    listener = VoiceListener.__new__(VoiceListener)
    listener.activity_callback = lambda phase, level: events.append((phase, level))
    listener.energy_threshold = 0.01
    listener._last_activity_at = 0.0
    listener._last_activity_phase = ""

    listener._emit_activity("recording", 0.02, force=True)

    assert events == [("recording", 1.0)]
