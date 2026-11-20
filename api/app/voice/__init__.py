"""Voice adapters: STT, TTS, VAD with local-first and hosted fallbacks."""

from app.voice.factory import get_voice_stack

__all__ = ["get_voice_stack"]
