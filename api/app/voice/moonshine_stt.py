from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from app.voice.base import TranscriptPartial


class MoonshineSTTAdapter:
    name = "moonshine-onnx-tiny"
    sample_rate = 16000

    def __init__(self, model_name: str = "moonshine/tiny") -> None:
        import moonshine_onnx as moonshine

        self._moonshine = moonshine
        self._model_name = model_name
        # Warm with package asset once.
        asset = moonshine.ASSETS_DIR / "beckett.wav"
        if asset.exists():
            moonshine.transcribe(asset, model_name)

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> TranscriptPartial:
        return await asyncio.to_thread(self._transcribe_sync, pcm16, sample_rate)

    def _transcribe_sync(self, pcm16: bytes, sample_rate: int) -> TranscriptPartial:
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != self.sample_rate and audio.size:
            # Linear resample for mismatched client rates.
            duration = audio.size / float(sample_rate)
            target = max(1, int(duration * self.sample_rate))
            x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
            x_new = np.linspace(0.0, 1.0, num=target, endpoint=False)
            audio = np.interp(x_new, x_old, audio).astype(np.float32)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            sf.write(path, audio, self.sample_rate)
            result = self._moonshine.transcribe(path, self._model_name)
            text = result[0] if isinstance(result, list) and result else str(result)
            return TranscriptPartial(text=text.strip(), is_final=True)
        finally:
            path.unlink(missing_ok=True)
