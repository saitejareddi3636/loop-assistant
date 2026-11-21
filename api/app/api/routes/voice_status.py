from __future__ import annotations

import traceback
from typing import Any

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["voice"])


@router.get("/voice/diagnostics")
async def voice_diagnostics() -> dict[str, Any]:
    """Report which STT/TTS backends load and why fallbacks occur.

    Safe for production probes: does not mutate customer data.
    """
    settings = get_settings()
    result: dict[str, Any] = {
        "voice_backend_setting": settings.voice_backend,
        "voice_stt_setting": settings.voice_stt,
        "voice_lazy_load": settings.voice_lazy_load,
        "attempts": [],
        "active": None,
    }

    # Probe Moonshine explicitly
    moon: dict[str, Any] = {"backend": "moonshine-onnx-tiny", "ok": False}
    try:
        from app.voice.moonshine_stt import MoonshineSTTAdapter

        adapter = MoonshineSTTAdapter()
        moon["ok"] = True
        moon["name"] = adapter.name
    except Exception as exc:  # noqa: BLE001
        moon["error"] = f"{type(exc).__name__}: {exc}"
        moon["traceback_tail"] = traceback.format_exc().strip().splitlines()[-6:]
    result["attempts"].append(moon)

    groq: dict[str, Any] = {"backend": "groq-whisper", "ok": False}
    try:
        from app.voice.groq_stt import GroqWhisperSTTAdapter

        if not settings.effective_llm_api_key and not settings.groq_api_key:
            groq["error"] = "GROQ_API_KEY missing"
        else:
            adapter = GroqWhisperSTTAdapter()
            groq["ok"] = True
            groq["name"] = adapter.name
    except Exception as exc:  # noqa: BLE001
        groq["error"] = f"{type(exc).__name__}: {exc}"
        groq["traceback_tail"] = traceback.format_exc().strip().splitlines()[-6:]
    result["attempts"].append(groq)

    pocket: dict[str, Any] = {"backend": "pocket-tts", "ok": False}
    try:
        from app.voice.pocket_tts import PocketTTSAdapter

        adapter = PocketTTSAdapter(voice=settings.voice_tts_voice)
        pocket["ok"] = True
        pocket["name"] = adapter.name
        pocket["sample_rate"] = adapter.sample_rate
    except Exception as exc:  # noqa: BLE001
        pocket["error"] = f"{type(exc).__name__}: {exc}"
        pocket["traceback_tail"] = traceback.format_exc().strip().splitlines()[-6:]
    result["attempts"].append(pocket)

    try:
        from app.voice.factory import get_voice_stack

        stack = get_voice_stack(force_reload=True)
        result["active"] = {
            "backend": stack.backend,
            "stt": stack.stt.name,
            "tts": stack.tts.name,
            "vad": stack.vad.name,
        }
    except Exception as exc:  # noqa: BLE001
        result["active_error"] = f"{type(exc).__name__}: {exc}"

    # Interpretation for reviewers (factory no longer silently falls back to hosted).
    if moon.get("ok"):
        result["recommendation"] = (
            "Moonshine Tiny loads successfully. Keep VOICE_BACKEND=local|auto so production "
            "uses moonshine-onnx-tiny. Hosted Whisper requires VOICE_BACKEND=hosted or VOICE_STT=groq."
        )
    elif groq.get("ok"):
        result["recommendation"] = (
            "Moonshine Tiny failed to load on this host. Voice will fail under VOICE_BACKEND=auto|local "
            "because silent hosted fallback is disabled. Fix Moonshine deps/weights, or set "
            f"VOICE_BACKEND=hosted explicitly. Moonshine error: {moon.get('error')}"
        )
    else:
        result["recommendation"] = "No STT backend available — voice will fail."

    result["fallback_policy"] = (
        "No silent Groq fallback. local|auto|moonshine require Moonshine; "
        "hosted|groq require Whisper."
    )
    return result
