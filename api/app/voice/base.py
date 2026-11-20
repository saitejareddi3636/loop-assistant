from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol


@dataclass
class TranscriptPartial:
    text: str
    is_final: bool = False
    confidence: float | None = None


@dataclass
class AudioChunk:
    pcm16: bytes
    sample_rate: int
    sequence: int
    generation: int = 0


@dataclass
class VoiceMetrics:
    stt_provider: str
    tts_provider: str
    vad_provider: str
    stt_latency_ms: float | None = None
    tts_first_audio_ms: float | None = None
    tts_total_ms: float | None = None
    interrupt_stop_ms: float | None = None
    rss_mb: float | None = None
    notes: list[str] = field(default_factory=list)


class STTAdapter(Protocol):
    name: str
    sample_rate: int

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> TranscriptPartial: ...


class TTSAdapter(Protocol):
    name: str
    sample_rate: int

    def synthesize_stream(self, text: str) -> AsyncIterator[bytes]: ...


class VADAdapter(Protocol):
    name: str
    sample_rate: int
    frame_samples: int

    def speech_probability(self, pcm_f32_frame: bytes) -> float: ...
