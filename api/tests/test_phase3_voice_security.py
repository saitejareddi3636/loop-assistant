from __future__ import annotations

import numpy as np
import pytest

from app.security.rate_limit import SlidingWindowRateLimiter
from app.security.sessions import issue_session_token, verify_session_token


def test_session_token_roundtrip():
    token = issue_session_token("abc-123", ttl_seconds=60)
    assert verify_session_token(token.token, "abc-123")
    assert not verify_session_token(token.token, "other")
    assert not verify_session_token("not-a-token", "abc-123")


def test_rate_limiter_blocks():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("c1")
    assert limiter.allow("c1")
    assert not limiter.allow("c1")
    assert limiter.allow("c2")


@pytest.mark.asyncio
async def test_moonshine_and_vad_adapters():
    from app.voice.moonshine_stt import MoonshineSTTAdapter
    from app.voice.silero_vad import SileroVADAdapter
    import moonshine_onnx as moonshine
    import soundfile as sf

    vad = SileroVADAdapter()
    frame = (0.15 * np.sin(2 * np.pi * 180 * np.arange(512) / 16000)).astype(np.float32)
    assert 0.0 <= vad.speech_probability(frame.tobytes()) <= 1.0

    audio, sr = sf.read(moonshine.ASSETS_DIR / "beckett.wav", dtype="float32")
    if audio.ndim > 1:
        audio = audio[:, 0]
    pcm16 = (np.clip(audio, -1, 1) * 32767.0).astype(np.int16).tobytes()
    stt = MoonshineSTTAdapter()
    result = await stt.transcribe(pcm16, sr)
    assert "fail" in result.text.lower() or "tried" in result.text.lower()


def test_estimate_chat_cost():
    from app.observability.metrics import estimate_chat_cost

    cost = estimate_chat_cost(model="openai/gpt-oss-120b", prompt_chars=400, completion_chars=200)
    assert cost["prompt_tokens_est"] == 100
    assert cost["estimated_cost_usd"] >= 0
