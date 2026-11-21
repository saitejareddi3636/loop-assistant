"""On-demand chat TTS — Pocket TTS WAV, never auto-plays from the agent."""

from __future__ import annotations

import io
import time
import uuid
import wave

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SpeakRequest
from app.config import get_settings
from app.db.models import Conversation
from app.db.session import get_session
from app.security.rate_limit import speak_limiter
from app.security.sessions import verify_session_token

router = APIRouter(prefix="/conversations", tags=["voice"])

_MAX_CHARS = 1200


@router.post("/{conversation_id}/speak")
async def speak_message(
    conversation_id: uuid.UUID,
    body: SpeakRequest,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Synthesize a short reply with Pocket TTS for the speaker button.

    Does **not** create messages or run the agent.
    """
    token = x_session_token or ""
    if not verify_session_token(token, str(conversation_id)):
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    if not speak_limiter.allow(str(conversation_id)):
        raise HTTPException(status_code=429, detail="TTS rate limit exceeded")

    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to speak")
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS].rsplit(" ", 1)[0] or text[:_MAX_CHARS]

    settings = get_settings()
    try:
        from app.voice.pocket_tts import PocketTTSAdapter, speakable_sentences

        tts = PocketTTSAdapter(voice=settings.voice_tts_voice)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"TTS unavailable: {exc}") from exc

    # Cap to a few sentences so click-to-speak stays snappy.
    sentences = speakable_sentences(text)[:4]
    speak_text = " ".join(sentences).strip()
    if not speak_text:
        raise HTTPException(status_code=400, detail="Nothing speakable in that text")

    t0 = time.perf_counter()
    chunks: list[bytes] = []
    try:
        async for piece in tts.synthesize_stream(speak_text):
            if piece:
                chunks.append(piece)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"TTS failed: {exc}") from exc

    pcm = b"".join(chunks)
    if len(pcm) < 4:
        raise HTTPException(status_code=503, detail="TTS returned no audio")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(tts.sample_rate))
        wf.writeframes(pcm)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return Response(
        content=buf.getvalue(),
        media_type="audio/wav",
        headers={
            "X-TTS-Provider": tts.name,
            "X-TTS-Ms": str(elapsed_ms),
            "Cache-Control": "no-store",
        },
    )
