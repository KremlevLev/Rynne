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


def test_silero_speed_uses_native_ssml_instead_of_audio_postprocessing(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Audio:
        def numpy(self):
            return np.zeros(240, dtype=np.float32)

    class Model:
        def apply_tts(self, **options):
            captured.update(options)
            return Audio()

    monkeypatch.setattr(tts, "_get_silero_engine", lambda: Model())
    monkeypatch.setattr(tts, "_play_audio", lambda audio, sample_rate: True)
    monkeypatch.setattr(tts, "_speech_interrupted", False)

    assert tts.speak(
        "Привет & добро пожаловать",
        speaker="xenia",
        language="ru",
        speed=1.3,
    )

    assert "text" not in captured
    assert 'rate="fast"' in captured["ssml_text"]
    assert "&amp;" in captured["ssml_text"]


def test_silero_speed_scale_maps_to_natural_presets() -> None:
    assert tts._silero_prosody_rate(0.7) == "x-slow"
    assert tts._silero_prosody_rate(0.85) == "slow"
    assert tts._silero_prosody_rate(1.0) is None
    assert tts._silero_prosody_rate(1.25) == "fast"
    assert tts._silero_prosody_rate(1.55) == "x-fast"


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
