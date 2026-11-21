"""Dictation-only transcription — Moonshine Tiny, no LLM / tools / messages."""

from __future__ import annotations

import io
import struct
import time
import uuid
import wave

import numpy as np
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import TranscribeResponse
from app.config import get_settings
from app.db.models import Conversation
from app.db.session import get_session
from app.security.rate_limit import transcribe_limiter
from app.security.sessions import verify_session_token

router = APIRouter(prefix="/conversations", tags=["voice"])

_MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MiB
_MAX_SECONDS = 60.0


def _pcm16_duration_ms(pcm: bytes, sample_rate: int) -> float:
    if sample_rate <= 0 or len(pcm) < 2:
        return 0.0
    return (len(pcm) / 2 / sample_rate) * 1000.0


def _wav_to_pcm16(data: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(data), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if sampwidth != 2:
        raise HTTPException(status_code=400, detail="Only 16-bit PCM WAV is supported")
    audio = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return audio.tobytes(), int(rate)


def _raw_pcm_to_pcm16(data: bytes, sample_rate: int) -> tuple[bytes, int]:
    if len(data) % 2 != 0:
        raise HTTPException(status_code=400, detail="Invalid raw PCM16 payload")
    return data, sample_rate


@router.post("/{conversation_id}/transcribe", response_model=TranscribeResponse)
async def transcribe_dictation(
    conversation_id: uuid.UUID,
    file: UploadFile = File(...),
    sample_rate: int = Form(default=16000),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    session: AsyncSession = Depends(get_session),
) -> TranscribeResponse:
    """Transcribe audio for composer preview only.

    Does **not** run LangGraph, execute tools, or persist user/assistant messages.
    """
    token = x_session_token or ""
    if not verify_session_token(token, str(conversation_id)):
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    if not transcribe_limiter.allow(str(conversation_id)):
        raise HTTPException(status_code=429, detail="Transcription rate limit exceeded")

    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio upload too large")

    content_type = (file.content_type or "").lower()
    filename = (file.filename or "").lower()
    try:
        if "wav" in content_type or filename.endswith(".wav") or payload[:4] == b"RIFF":
            pcm16, rate = _wav_to_pcm16(payload)
        elif (
            "octet-stream" in content_type
            or filename.endswith(".pcm")
            or filename.endswith(".raw")
        ):
            pcm16, rate = _raw_pcm_to_pcm16(payload, sample_rate)
        else:
            # Prefer explicit WAV from the client; reject opaque containers so we
            # never silently depend on ffmpeg / hosted STT.
            raise HTTPException(
                status_code=415,
                detail="Upload audio/wav (PCM16 mono) or raw PCM16 with sample_rate",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse audio: {exc}") from exc

    duration_ms = _pcm16_duration_ms(pcm16, rate)
    if duration_ms < 150:
        raise HTTPException(status_code=400, detail="Recording too short")
    if duration_ms > _MAX_SECONDS * 1000:
        raise HTTPException(status_code=400, detail="Recording too long")

    # Dictation always uses Moonshine Tiny — never hosted STT.
    from app.voice.moonshine_stt import MoonshineSTTAdapter

    settings = get_settings()
    stt = MoonshineSTTAdapter()
    t0 = time.perf_counter()
    try:
        result = await stt.transcribe(pcm16, rate)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"STT failed: {exc}") from exc
    stt_ms = (time.perf_counter() - t0) * 1000

    return TranscribeResponse(
        text=(result.text or "").strip(),
        stt_ms=round(stt_ms, 1),
        stt_provider=stt.name,
        sample_rate=rate or settings.voice_input_sample_rate,
        duration_ms=round(duration_ms, 1),
    )


def build_silence_wav(duration_s: float = 0.3, sample_rate: int = 16000) -> bytes:
    """Test helper — not used by the route."""
    n = int(duration_s * sample_rate)
    pcm = struct.pack(f"<{n}h", *([0] * n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()
