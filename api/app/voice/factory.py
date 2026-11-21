from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from app.config import get_settings
from app.voice.base import STTAdapter, TTSAdapter, VADAdapter

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_stack: "VoiceStack | None" = None


@dataclass
class VoiceStack:
    stt: STTAdapter
    tts: TTSAdapter
    vad: VADAdapter
    backend: str
    stt_error: str | None = None


def _want_local_stt(prefer: str, stt_pref: str) -> bool:
    if stt_pref in {"groq", "hosted"}:
        return False
    if stt_pref in {"local", "moonshine"}:
        return True
    return prefer in {"local", "auto", "moonshine"}


def _want_hosted_stt(prefer: str, stt_pref: str) -> bool:
    """Hosted STT only when explicitly requested — never as a silent fallback."""
    if stt_pref in {"groq", "hosted"}:
        return True
    if stt_pref in {"local", "moonshine"}:
        return False
    return prefer in {"hosted", "groq"}


def _build_stack() -> VoiceStack:
    settings = get_settings()
    prefer = settings.voice_backend.lower().strip()
    stt_pref = settings.voice_stt.lower().strip()
    stt_error: str | None = None

    # VAD
    try:
        from app.voice.silero_vad import SileroVADAdapter

        vad: VADAdapter = SileroVADAdapter()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Silero VAD unavailable (%s); using energy VAD", exc)
        from app.voice.silero_vad import EnergyVADAdapter

        vad = EnergyVADAdapter()

    stt: STTAdapter | None = None
    if _want_local_stt(prefer, stt_pref):
        try:
            from app.voice.moonshine_stt import MoonshineSTTAdapter

            stt = MoonshineSTTAdapter()
        except Exception as exc:  # noqa: BLE001
            stt_error = f"{type(exc).__name__}: {exc}"
            logger.error("Moonshine STT failed to load: %s", stt_error)
            if not _want_hosted_stt(prefer, stt_pref):
                raise RuntimeError(
                    "Moonshine Tiny STT failed and hosted fallback is disabled. "
                    "Fix local STT deps/weights, or set VOICE_BACKEND=hosted / "
                    f"VOICE_STT=groq explicitly. Cause: {stt_error}"
                ) from exc

    if stt is None and _want_hosted_stt(prefer, stt_pref):
        try:
            from app.voice.groq_stt import GroqWhisperSTTAdapter

            stt = GroqWhisperSTTAdapter()
            if stt_error:
                logger.warning(
                    "Using explicit hosted STT after Moonshine failure: %s", stt_error
                )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Groq Whisper STT unavailable: {exc}") from exc

    if stt is None:
        raise RuntimeError(
            f"No STT backend selected for VOICE_BACKEND={prefer!r} VOICE_STT={stt_pref!r}. "
            "Use local|auto|moonshine for Moonshine Tiny, or hosted|groq for Whisper."
            + (f" Last Moonshine error: {stt_error}" if stt_error else "")
        )

    # TTS
    tts: TTSAdapter | None = None
    if prefer in {"local", "auto", "moonshine", "pocket", "hosted", "groq"}:
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
    return VoiceStack(stt=stt, tts=tts, vad=vad, backend=backend, stt_error=stt_error)


def get_voice_stack(force_reload: bool = False) -> VoiceStack:
    global _stack
    with _lock:
        if _stack is None or force_reload:
            _stack = _build_stack()
        return _stack
