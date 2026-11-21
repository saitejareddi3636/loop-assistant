"""Dictation transcription must never create messages or invoke the agent."""

from __future__ import annotations

import io
import uuid
import wave
from unittest.mock import AsyncMock, patch

import pytest

from app.db import session as db_session
from app.db.models import Message
from app.voice.base import TranscriptPartial
from sqlalchemy import func, select


def _tone_wav(duration_s: float = 0.5, sample_rate: int = 16000, freq: float = 440.0) -> bytes:
    import math
    import struct

    n = int(duration_s * sample_rate)
    frames = bytearray()
    for i in range(n):
        sample = int(12000 * math.sin(2 * math.pi * freq * i / sample_rate))
        frames.extend(struct.pack("<h", sample))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_transcribe_requires_session_token(client):
    conv = (
        await client.post("/api/conversations", json={"customer_id": "cust_pro_001"})
    ).json()
    cid = conv["id"]
    wav = _tone_wav()
    res = await client.post(
        f"/api/conversations/{cid}/transcribe",
        files={"file": ("dictation.wav", wav, "audio/wav")},
        data={"sample_rate": "16000"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_transcribe_only_returns_text_no_messages(client):
    conv = (
        await client.post("/api/conversations", json={"customer_id": "cust_pro_001"})
    ).json()
    cid = conv["id"]
    token = conv["session_token"]
    wav = _tone_wav()

    fake = TranscriptPartial(text="refund invoice INV-1042 please", is_final=True)
    mock_stt = AsyncMock()
    mock_stt.name = "moonshine-onnx-tiny"
    mock_stt.transcribe = AsyncMock(return_value=fake)
    with patch("app.voice.moonshine_stt.MoonshineSTTAdapter", return_value=mock_stt):
        res = await client.post(
            f"/api/conversations/{cid}/transcribe",
            headers={"X-Session-Token": token},
            files={"file": ("dictation.wav", wav, "audio/wav")},
            data={"sample_rate": "16000"},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["text"] == "refund invoice INV-1042 please"
    assert body["stt_provider"] == "moonshine-onnx-tiny"
    assert body["duration_ms"] > 0
    mock_stt.transcribe.assert_awaited_once()

    detail = (await client.get(f"/api/conversations/{cid}")).json()
    assert detail["messages"] == []

    async with db_session.async_session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Message).where(Message.conversation_id == uuid.UUID(cid))
        )
    assert count == 0


@pytest.mark.asyncio
async def test_transcribe_rejects_short_audio(client):
    conv = (
        await client.post("/api/conversations", json={"customer_id": "cust_pro_001"})
    ).json()
    cid = conv["id"]
    token = conv["session_token"]
    wav = _tone_wav(duration_s=0.05)
    res = await client.post(
        f"/api/conversations/{cid}/transcribe",
        headers={"X-Session-Token": token},
        files={"file": ("dictation.wav", wav, "audio/wav")},
        data={"sample_rate": "16000"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_send_after_dictation_uses_chat_pipeline(client):
    """Acceptance: transcript preview is separate; Send creates exactly one user turn."""
    conv = (
        await client.post("/api/conversations", json={"customer_id": "cust_pro_001"})
    ).json()
    cid = conv["id"]
    token = conv["session_token"]
    wav = _tone_wav()

    mock_stt = AsyncMock()
    mock_stt.name = "moonshine-onnx-tiny"
    mock_stt.transcribe = AsyncMock(
        return_value=TranscriptPartial(text="I was charged twice on INV-1042", is_final=True)
    )
    with patch("app.voice.moonshine_stt.MoonshineSTTAdapter", return_value=mock_stt):
        tr = await client.post(
            f"/api/conversations/{cid}/transcribe",
            headers={"X-Session-Token": token},
            files={"file": ("dictation.wav", wav, "audio/wav")},
            data={"sample_rate": "16000"},
        )
    assert tr.status_code == 200
    text = tr.json()["text"]
    # User could edit before send:
    edited = text.replace("INV-1042", "INV-9999")

    turn = await client.post(
        f"/api/conversations/{cid}/turns",
        json={"text": edited, "client_turn_id": str(uuid.uuid4())},
    )
    assert turn.status_code == 200

    import asyncio

    detail = None
    for _ in range(40):
        detail = (await client.get(f"/api/conversations/{cid}")).json()
        if any(m["role"] == "assistant" for m in detail["messages"]):
            break
        await asyncio.sleep(0.1)
    assert detail is not None
    users = [m for m in detail["messages"] if m["role"] == "user"]
    assert len(users) == 1
    assert "INV-9999" in users[0]["content"]
