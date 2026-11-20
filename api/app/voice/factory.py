from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from app.config import get_settings
from app.voice.base import STTAdapter, TTSAdapter, VADAdapter

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_stack: VoiceStack | None = None


@dataclass
class VoiceStack:
    stt: STTAdapter
    tts: TTSAdapter
    vad: VADAdapter
    backend: str


def _build_stack() -> VoiceStack:
    settings = get_settings()
    prefer = settings.voice_backend.lower().strip()

    # VAD
    try:
        from app.voice.silero_vad import SileroVADAdapter

        vad: VADAdapter = SileroVADAdapter()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Silero VAD unavailable (%s); using energy VAD", exc)
        from app.voice.silero_vad import EnergyVADAdapter

        vad = EnergyVADAdapter()

    # STT
    stt: STTAdapter | None = None
    stt_pref = settings.voice_stt.lower().strip()
    if stt_pref in {"groq", "hosted"}:
        try:
            from app.voice.groq_stt import GroqWhisperSTTAdapter

            stt = GroqWhisperSTTAdapter()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Groq Whisper STT unavailable (%s); trying local", exc)
    if stt is None and prefer in {"local", "auto", "moonshine"}:
        try:
            from app.voice.moonshine_stt import MoonshineSTTAdapter

            stt = MoonshineSTTAdapter()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Moonshine STT failed (%s)", exc)
    if stt is None and prefer in {"auto", "hosted", "groq"}:
        from app.voice.groq_stt import GroqWhisperSTTAdapter

        stt = GroqWhisperSTTAdapter()
    if stt is None:
        # last resort: try hosted even if prefer was local
        try:
            from app.voice.groq_stt import GroqWhisperSTTAdapter

            stt = GroqWhisperSTTAdapter()
            logger.warning("Falling back to Groq Whisper STT")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"No STT backend available: {exc}") from exc

    # TTS
    tts: TTSAdapter | None = None
    if prefer in {"local", "auto", "moonshine", "pocket"}:
        try:
            from app.voice.pocket_tts import PocketTTSAdapter

            tts = PocketTTSAdapter(voice=settings.voice_tts_voice)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pocket TTS failed (%s)", exc)
    if tts is None:
        from app.voice.pocket_tts import NullTTSAdapter

        tts = NullTTSAdapter()
        logger.warning("Using null TTS; browser Web Speech can fill in")

    backend = f"stt={stt.name};tts={tts.name};vad={vad.name}"
    logger.info("Voice stack ready: %s", backend)
    return VoiceStack(stt=stt, tts=tts, vad=vad, backend=backend)


def get_voice_stack(force_reload: bool = False) -> VoiceStack:
    global _stack
    with _lock:
        if _stack is None or force_reload:
            _stack = _build_stack()
        return _stack
