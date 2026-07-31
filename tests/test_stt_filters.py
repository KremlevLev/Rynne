from modules.audio.stt import is_likely_whisper_hallucination


def test_common_whisper_caption_hallucinations_are_rejected() -> None:
    assert is_likely_whisper_hallucination("ТРЕВОЖНАЯ МУЗЫКА")
    assert is_likely_whisper_hallucination("Субтитры создавал DimaTorzok")
    assert is_likely_whisper_hallucination("[Музыка]")
    assert is_likely_whisper_hallucination("Спасибо за просмотр!")


def test_real_commands_that_mention_music_or_subtitles_survive() -> None:
    assert not is_likely_whisper_hallucination("Включи тревожную музыку")
    assert not is_likely_whisper_hallucination("Найди субтитры к фильму")
