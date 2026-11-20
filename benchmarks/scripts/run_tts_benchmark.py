#!/usr/bin/env python3
"""Benchmark Pocket TTS separately from STT models."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import psutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from metrics import measure_inference, last_measurement  # noqa: E402


def _host_info() -> dict[str, Any]:
    mem = psutil.virtual_memory()
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def run_pocket(
    voice: str,
    utterances: list[str],
    warmup_runs: int,
    timed_runs: int,
    sample_resources: bool,
    raw_audio_dir: Path | None,
) -> dict[str, Any]:
    from pocket_tts import TTSModel

    rss_before = psutil.Process().memory_info().rss / (1024 * 1024)
    t0 = time.perf_counter()
    model = TTSModel.load_model()
    voice_state = model.get_state_for_audio_prompt(voice)
    load_s = time.perf_counter() - t0
    rss_after = psutil.Process().memory_info().rss / (1024 * 1024)
    sample_rate = int(model.sample_rate)
    print(f"Pocket TTS load: {load_s:.2f}s  RSS {rss_before:.0f} → {rss_after:.0f} MB  sr={sample_rate}")

    # Warmup
    warm = utterances[0]
    for _ in range(warmup_runs):
        if hasattr(model, "generate_audio_stream"):
            for _chunk in model.generate_audio_stream(voice_state, warm):
                pass
        else:
            model.generate_audio(voice_state, warm)

    results: list[dict[str, Any]] = []
    for idx, text in enumerate(utterances):
        first_audio_runs: list[float] = []
        total_runs: list[float] = []
        audio_durations: list[float] = []
        resource_rows: list[dict[str, float]] = []

        for run_i in range(timed_runs):
            samples = 0
            first = None
            t_start = time.perf_counter()
            with measure_inference(sample_resources=sample_resources):
                if hasattr(model, "generate_audio_stream"):
                    chunks: list[np.ndarray] = []
                    for chunk in model.generate_audio_stream(voice_state, text):
                        if first is None:
                            first = time.perf_counter() - t_start
                        arr = (
                            chunk.detach().cpu().numpy()
                            if hasattr(chunk, "detach")
                            else np.asarray(chunk)
                        )
                        arr = np.asarray(arr, dtype=np.float32).reshape(-1)
                        samples += arr.size
                        chunks.append(arr)
                    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
                else:
                    audio_t = model.generate_audio(voice_state, text)
                    first = time.perf_counter() - t_start
                    audio = (
                        audio_t.detach().cpu().numpy()
                        if hasattr(audio_t, "detach")
                        else np.asarray(audio_t)
                    )
                    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
                    samples = audio.size
            m = last_measurement()
            total = float(m["latency_s"])
            first_audio_runs.append(float(first if first is not None else total))
            total_runs.append(total)
            audio_durations.append(samples / float(sample_rate) if sample_rate else 0.0)
            resource_rows.append(m.get("resources") or {})
            print(
                f"  utt{idx} run {run_i + 1}: first={first_audio_runs[-1]:.3f}s "
                f"total={total:.3f}s audio={audio_durations[-1]:.2f}s"
            )

            if raw_audio_dir is not None and run_i == 0:
                raw_audio_dir.mkdir(parents=True, exist_ok=True)
                out = raw_audio_dir / f"pocket_utt{idx}.wav"
                import soundfile as sf

                sf.write(out, np.clip(audio, -1.0, 1.0), sample_rate)

        rtf = [
            (tot / aud) if aud > 0 else None
            for tot, aud in zip(total_runs, audio_durations)
        ]
        results.append(
            {
                "text": text,
                "first_audio_s_runs": [round(x, 4) for x in first_audio_runs],
                "first_audio_s_mean": round(statistics.mean(first_audio_runs), 4),
                "total_s_runs": [round(x, 4) for x in total_runs],
                "total_s_mean": round(statistics.mean(total_runs), 4),
                "audio_duration_s_mean": round(statistics.mean(audio_durations), 4),
                "realtime_factor_mean": round(
                    statistics.mean([x for x in rtf if x is not None]), 4
                )
                if any(x is not None for x in rtf)
                else None,
                "resources_mean": {
                    "rss_mb_peak_mean": round(
                        statistics.mean(r.get("rss_mb_peak", 0.0) for r in resource_rows), 1
                    ),
                    "cpu_percent_peak_mean": round(
                        statistics.mean(r.get("cpu_percent_peak", 0.0) for r in resource_rows), 1
                    ),
                },
            }
        )

    return {
        "model_id": "pocket_tts",
        "display_name": "Pocket TTS",
        "voice": voice,
        "sample_rate": sample_rate,
        "load_s": round(load_s, 3),
        "rss_mb_before_load": round(rss_before, 1),
        "rss_mb_after_load": round(rss_after, 1),
        "rss_mb_delta": round(rss_after - rss_before, 1),
        "first_audio_s_mean": round(
            statistics.mean(r["first_audio_s_mean"] for r in results), 4
        ),
        "total_s_mean": round(statistics.mean(r["total_s_mean"] for r in results), 4),
        "pass_first_audio_lt_0_5s": all(r["first_audio_s_mean"] < 0.5 for r in results),
        "utterances": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "benchmark.yaml",
    )
    parser.add_argument(
        "--save-audio",
        action="store_true",
        help="Write first-run WAVs under results/raw_audio/ (gitignored).",
    )
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    tts_cfg = cfg["tts"][0]
    raw_dir = ROOT / "results" / "raw_audio" if args.save_audio else None

    report = {
        "suite": "loopp-tts-benchmark",
        "device_label": cfg.get("device_label"),
        "host": _host_info(),
        "config": {
            "warmup_runs": cfg.get("warmup_runs", 1),
            "timed_runs": cfg.get("timed_runs", 3),
        },
        "models": [
            run_pocket(
                voice=tts_cfg.get("voice", "alba"),
                utterances=list(tts_cfg["utterances"]),
                warmup_runs=int(cfg.get("warmup_runs", 1)),
                timed_runs=int(cfg.get("timed_runs", 3)),
                sample_resources=bool(
                    cfg.get("resources", {}).get("sample_cpu_during_infer", True)
                ),
                raw_audio_dir=raw_dir,
            )
        ],
    }

    out = ROOT / cfg["outputs"]["tts_json"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
