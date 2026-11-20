from __future__ import annotations

import io
import wave

import httpx

from app.config import get_settings
from app.voice.base import TranscriptPartial


class GroqWhisperSTTAdapter:
    """Hosted STT fallback via Groq OpenAI-compatible audio transcriptions."""

    name = "groq-whisper"
    sample_rate = 16000

    def __init__(self, model: str = "whisper-large-v3-turbo") -> None:
        settings = get_settings()
        self._api_key = settings.effective_llm_api_key
        self._base_url = settings.llm_base_url.rstrip("/")
        if "groq.com" not in self._base_url:
            self._base_url = "https://api.groq.com/openai/v1"
        self._model = model
        if not self._api_key:
            raise RuntimeError("GROQ_API_KEY required for hosted STT fallback")

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> TranscriptPartial:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16)
        payload = buf.getvalue()

        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"file": ("utterance.wav", payload, "audio/wav")}
            data = {
                "model": self._model,
                "response_format": "json",
                "language": "en",
                "temperature": "0",
            }
            resp = await client.post(
                f"{self._base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                files=files,
                data=data,
            )
            resp.raise_for_status()
            body = resp.json()
        return TranscriptPartial(text=str(body.get("text", "")).strip(), is_final=True)
