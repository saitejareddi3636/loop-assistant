"""Voice factory must not silently fall back to hosted STT."""

from __future__ import annotations

import pytest


def test_auto_backend_does_not_silently_use_groq_when_moonshine_fails(monkeypatch):
    from app import config
    from app.voice import factory as factory_mod

    monkeypatch.setenv("VOICE_BACKEND", "auto")
    monkeypatch.setenv("VOICE_STT", "auto")
    config.get_settings.cache_clear()
    factory_mod._stack = None

    import app.voice.moonshine_stt as moon_mod
    import app.voice.silero_vad as vad_mod

    class BrokenMoonshine:
        def __init__(self, *a, **k):
            raise RuntimeError("simulated moonshine missing weights")

    class FakeVad:
        name = "energy-vad"

        def is_speech(self, *a, **k):
            return False

    monkeypatch.setattr(moon_mod, "MoonshineSTTAdapter", BrokenMoonshine)
    monkeypatch.setattr(vad_mod, "SileroVADAdapter", FakeVad)
    monkeypatch.setattr(vad_mod, "EnergyVADAdapter", FakeVad)

    with pytest.raises(RuntimeError, match="hosted fallback is disabled"):
        factory_mod.get_voice_stack(force_reload=True)

    factory_mod._stack = None
    config.get_settings.cache_clear()


def test_hosted_backend_uses_groq_without_requiring_moonshine(monkeypatch):
    from app import config
    from app.voice import factory as factory_mod
    from app.voice.base import TranscriptPartial

    monkeypatch.setenv("VOICE_BACKEND", "hosted")
    monkeypatch.setenv("VOICE_STT", "groq")
    config.get_settings.cache_clear()
    factory_mod._stack = None

    import app.voice.groq_stt as groq_mod
    import app.voice.pocket_tts as pocket_mod
    import app.voice.silero_vad as vad_mod

    class FakeGroq:
        name = "groq-whisper"

        async def transcribe(self, pcm16: bytes, sample_rate: int) -> TranscriptPartial:
            return TranscriptPartial(text="ok", is_final=True)

    class FakePocket:
        name = "pocket-tts"
        sample_rate = 24000

        def __init__(self, voice: str = "alba") -> None:
            pass

        async def synthesize_stream(self, text: str):
            if False:
                yield b""

    class FakeVad:
        name = "energy-vad"

        def is_speech(self, *a, **k):
            return False

    monkeypatch.setattr(groq_mod, "GroqWhisperSTTAdapter", FakeGroq)
    monkeypatch.setattr(pocket_mod, "PocketTTSAdapter", FakePocket)
    monkeypatch.setattr(vad_mod, "SileroVADAdapter", FakeVad)

    stack = factory_mod.get_voice_stack(force_reload=True)
    assert stack.stt.name == "groq-whisper"
    assert "groq-whisper" in stack.backend

    factory_mod._stack = None
    config.get_settings.cache_clear()
