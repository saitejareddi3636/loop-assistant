from __future__ import annotations

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.security.rate_limit import voice_start_limiter
from app.security.sessions import verify_session_token
from app.voice.session import VoiceSession

router = APIRouter(tags=["voice"])


@router.websocket("/conversations/{conversation_id}/voice")
async def voice_socket(websocket: WebSocket, conversation_id: uuid.UUID) -> None:
    """Live Conversation mode only.

    Silero VAD end-of-utterance → STT → LangGraph → Pocket TTS.
    Dictation (composer mic) must use POST .../transcribe instead — never this socket.
    """
    token = websocket.query_params.get("token", "")
    if not verify_session_token(token, str(conversation_id)):
        await websocket.close(code=4401)
        return
    if not voice_start_limiter.allow(str(conversation_id)):
        await websocket.close(code=4429)
        return
    session = VoiceSession(websocket, conversation_id)
    try:
        await session.run()
    except WebSocketDisconnect:
        return
