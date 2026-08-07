from __future__ import annotations

import io
import wave

import numpy as np

import modules.audio.tts as tts


def _wav_bytes() -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(np.zeros(480, dtype=np.int16).tobytes())
    return target.getvalue()


def test_catalog_contains_local_and_groq_voice_pools(monkeypatch) -> None:
    monkeypatch.setattr(tts, "_groq_keys", lambda: ("gsk_test",))
    catalog = tts.get_tts_catalog()
    voices = catalog["voices"]

    assert len(voices) == 11
    assert {voice["id"] for voice in voices if voice["language"] == "ru"} == {
        "aidar", "baya", "kseniya", "xenia", "eugene",
    }
    assert {voice["id"] for voice in voices if voice["language"] == "en"} == {
        "autumn", "diana", "hannah", "austin", "daniel", "troy",
    }


def test_tts_settings_are_validated_and_persisted(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "tts-settings.json"
    monkeypatch.setattr(tts, "TTS_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(tts, "_tts_settings", tts.TTSSettings())

    updated = tts.update_tts_settings(
        language="en",
        en_voice="troy",
        speed=1.25,
        style="professional",
    )

    assert updated.en_voice == "troy"
    assert updated.speed == 1.25
    assert '"professional"' in settings_path.read_text(encoding="utf-8")


def test_local_time_stretch_changes_duration_without_another_model() -> None:
    source = np.sin(np.linspace(0, 20, 12000, dtype=np.float32))

    faster = tts._time_stretch(source, 1.3)
    slower = tts._time_stretch(source, 0.8)

    assert len(faster) < len(source)
    assert len(slower) > len(source)
    assert np.isfinite(faster).all()


def test_groq_orpheus_uses_selected_voice_speed_and_style(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status_code = 200
        content = _wav_bytes()

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(tts, "_groq_keys", lambda: ("gsk_test",))
    monkeypatch.setattr(tts.requests, "post", fake_post)
    monkeypatch.setattr(tts, "_play_audio", lambda audio, sample_rate: True)

    assert tts._speak_groq(
        "Welcome",
        voice="diana",
        speed=1.2,
        style="warm",
    )
    payload = captured["json"]
    assert payload["model"] == "canopylabs/orpheus-v1-english"
    assert payload["voice"] == "diana"
    assert payload["speed"] == 1.2
    assert payload["input"] == "[warm] Welcome"
