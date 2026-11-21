"""On-demand speak endpoint returns WAV without creating messages."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class _FakeTTS:
    name = "pocket-tts"
    sample_rate = 24000

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        pass

    async def synthesize_stream(self, text: str):
        n = int(self.sample_rate * 0.05) * 2
        yield b"\x00" * n


@pytest.mark.asyncio
async def test_speak_requires_session_token(client):
    conv = (
        await client.post("/api/conversations", json={"customer_id": "cust_pro_001"})
    ).json()
    res = await client.post(
        f"/api/conversations/{conv['id']}/speak",
        json={"text": "Hello there."},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_speak_returns_wav_no_messages(client):
    conv = (
        await client.post("/api/conversations", json={"customer_id": "cust_pro_001"})
    ).json()

    with (
        patch("app.voice.pocket_tts.PocketTTSAdapter", _FakeTTS),
        patch("app.voice.pocket_tts.speakable_sentences", return_value=["Hello there."]),
    ):
        res = await client.post(
            f"/api/conversations/{conv['id']}/speak",
            headers={"X-Session-Token": conv["session_token"]},
            json={"text": "Hello there."},
        )

    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("audio/wav")
    assert res.content[:4] == b"RIFF"
    assert res.headers.get("x-tts-provider") == "pocket-tts"

    detail = (await client.get(f"/api/conversations/{conv['id']}")).json()
    assert detail["messages"] == []
