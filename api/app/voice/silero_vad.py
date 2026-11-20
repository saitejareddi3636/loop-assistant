from __future__ import annotations

import numpy as np


class SileroVADAdapter:
    name = "silero-vad-lite"
    sample_rate = 16000
    frame_samples = 512  # 32 ms @ 16 kHz

    def __init__(self) -> None:
        from silero_vad_lite import SileroVAD

        self._vad = SileroVAD(self.sample_rate)

    def speech_probability(self, pcm_f32_frame: bytes) -> float:
        return float(self._vad.process(pcm_f32_frame))


class EnergyVADAdapter:
    """Fallback VAD using RMS energy — no model download."""

    name = "energy"
    sample_rate = 16000
    frame_samples = 512

    def __init__(self, threshold: float = 0.01) -> None:
        self.threshold = threshold

    def speech_probability(self, pcm_f32_frame: bytes) -> float:
        audio = np.frombuffer(pcm_f32_frame, dtype=np.float32)
        if audio.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(np.square(audio))))
        return 1.0 if rms >= self.threshold else 0.0
