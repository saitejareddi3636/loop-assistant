#!/usr/bin/env python3
"""Phase 3 local voice benchmark for Mac M2 (8 GB).

Reports STT/TTS/VAD latency and RSS. Does not require a microphone.
"""

from __future__ import annotations

import json
import resource
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)


def main() -> None:
    report: dict = {"device": "darwin-arm64", "rss_start_mb": round(rss_mb(), 1)}

    from silero_vad_lite import SileroVAD
    import numpy as np

    t0 = time.perf_counter()
    vad = SileroVAD(16000)
    report["vad_load_s"] = round(time.perf_counter() - t0, 3)
    frame = (0.2 * np.sin(2 * np.pi * 220 * np.arange(512) / 16000)).astype(np.float32)
    t0 = time.perf_counter()
    for _ in range(100):
        vad.process(frame.tobytes())
    report["vad_100_frames_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    import moonshine_onnx as moonshine

    asset = moonshine.ASSETS_DIR / "beckett.wav"
    moonshine.transcribe(asset, "moonshine/tiny")  # warm
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        text = moonshine.transcribe(asset, "moonshine/tiny")
        times.append(time.perf_counter() - t0)
    report["moonshine_warm_s"] = [round(t, 3) for t in times]
    report["moonshine_warm_mean_s"] = round(sum(times) / len(times), 3)
    report["moonshine_sample_text"] = text
    report["rss_after_stt_mb"] = round(rss_mb(), 1)

    from pocket_tts import TTSModel

    t0 = time.perf_counter()
    model = TTSModel.load_model()
    voice = model.get_state_for_audio_prompt("alba")
    report["tts_load_s"] = round(time.perf_counter() - t0, 3)
    utterance = "Your Pro refund for invoice INV-1042 is ready for confirmation."
    t0 = time.perf_counter()
    first = None
    samples = 0
    if hasattr(model, "generate_audio_stream"):
        for chunk in model.generate_audio_stream(voice, utterance):
            if first is None:
                first = time.perf_counter() - t0
            samples += int(chunk.numel()) if hasattr(chunk, "numel") else len(chunk)
    else:
        audio = model.generate_audio(voice, utterance)
        first = time.perf_counter() - t0
        samples = int(audio.numel())
    report["tts_first_audio_s"] = round(first or -1, 3)
    report["tts_total_s"] = round(time.perf_counter() - t0, 3)
    report["tts_audio_s"] = round(samples / model.sample_rate, 3)
    report["rss_after_tts_mb"] = round(rss_mb(), 1)
    report["pass_targets"] = {
        "tts_first_audio_lt_0_5s": (first or 99) < 0.5,
        "useful_audio_budget_lt_3s_note": "Depends on LLM; local TTS total measured separately",
        "rss_under_2gb": report["rss_after_tts_mb"] < 2048,
    }

    out = ROOT / "benchmarks" / "voice_m2.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
