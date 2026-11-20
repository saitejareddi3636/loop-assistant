from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import AsyncIterator, Iterator

import numpy as np

from app.voice.speech_normalize import normalize_for_speech

_MARKDOWN = re.compile(r"[*_`#>|~]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def speakable_sentences(text: str, max_chars: int = 220) -> list[str]:
    """Strip markdown, normalize IDs/currency for TTS, split into short sentences.

    Pocket TTS slows down sharply on long inputs, so synthesizing one short
    sentence at a time keeps generation near real time.
    """
    cleaned = _MARKDOWN.sub("", text)
    cleaned = cleaned.replace("\u2011", "-").replace("\u202f", " ").replace("\u00a0", " ")
    cleaned = normalize_for_speech(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    out: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(cleaned):
        sentence = sentence.strip()
        while len(sentence) > max_chars:
            cut = sentence.rfind(",", 0, max_chars)
            cut = cut if cut > 40 else max_chars
            out.append(sentence[: cut + 1].strip())
            sentence = sentence[cut + 1 :].strip()
        if sentence:
            out.append(sentence)
    return out


class PocketTTSAdapter:
    name = "pocket-tts"
    sample_rate = 24000

    def __init__(self, voice: str = "alba") -> None:
        from pocket_tts import TTSModel

        self._model = TTSModel.load_model()
        self.sample_rate = int(self._model.sample_rate)
        self._voice_state = self._model.get_state_for_audio_prompt(voice)

    def _iter_pcm16(self, text: str) -> Iterator[bytes]:
        model = self._model
        # Prefer native streaming if present.
        if hasattr(model, "generate_audio_stream"):
            for chunk in model.generate_audio_stream(self._voice_state, text):
                arr = chunk.detach().cpu().numpy() if hasattr(chunk, "detach") else np.asarray(chunk)
                arr = np.asarray(arr, dtype=np.float32).reshape(-1)
                pcm = np.clip(arr, -1.0, 1.0)
                yield (pcm * 32767.0).astype(np.int16).tobytes()
            return

        audio = model.generate_audio(self._voice_state, text)
        arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        arr = np.asarray(arr, dtype=np.float32).reshape(-1)
        pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        # Chunk ~100ms for progressive playback / interruptibility.
        frame = int(self.sample_rate * 0.1) * 2
        for i in range(0, len(pcm), frame):
            yield pcm[i : i + frame]

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        stop = threading.Event()

        def worker() -> None:
            try:
                for sentence in speakable_sentences(text):
                    for chunk in self._iter_pcm16(sentence):
                        if stop.is_set():
                            return
                        loop.call_soon_threadsafe(queue.put_nowait, chunk)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = loop.run_in_executor(None, worker)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            # On interrupt, stop generating at the next chunk boundary instead
            # of waiting for the whole reply to be synthesized.
            stop.set()
            await asyncio.shield(task)


class NullTTSAdapter:
    """Degraded TTS: yields no audio (UI can fall back to Web Speech)."""

    name = "null"
    sample_rate = 24000

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        if False:  # pragma: no cover
            yield b""
        return
