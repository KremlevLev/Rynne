import time

import modules.audio.tts as tts


def test_capture_guard_covers_playback_and_echo_tail(monkeypatch) -> None:
    monkeypatch.setattr(tts, "_tts_playing", True)
    monkeypatch.setattr(tts, "_tts_last_finished_at", float("-inf"))
    assert tts.is_tts_capture_blocked()

    monkeypatch.setattr(tts, "_tts_playing", False)
    monkeypatch.setattr(tts, "_tts_last_finished_at", time.monotonic())
    assert tts.is_tts_capture_blocked(cooldown_seconds=1.0)

    monkeypatch.setattr(tts, "_tts_last_finished_at", time.monotonic() - 2.0)
    assert not tts.is_tts_capture_blocked(cooldown_seconds=1.0)
