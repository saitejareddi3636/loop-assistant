#!/usr/bin/env python3
"""Run STT benchmarks: WER, latency, CPU/RAM, invoice-ID recall."""

from __future__ import annotations

import argparse
import csv
import gc
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from metrics import compute_wer, invoice_recall, measure_inference, last_measurement  # noqa: E402
from stt_backends import build_backend  # noqa: E402


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


def _load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _audio_path(audio_dir: Path, utt_id: str) -> Path:
    return audio_dir / f"{utt_id}.wav"


def evaluate_model(
    model_cfg: dict[str, Any],
    utterances: list[dict[str, Any]],
    audio_dir: Path,
    warmup_runs: int,
    timed_runs: int,
    sample_resources: bool,
) -> dict[str, Any]:
    backend = build_backend(model_cfg)
    print(f"\n=== {backend.display_name} ({backend.id}) ===")
    rss_before = psutil.Process().memory_info().rss / (1024 * 1024)
    load_s = backend.load()
    rss_after_load = psutil.Process().memory_info().rss / (1024 * 1024)
    print(f"  load: {load_s:.2f}s  RSS {rss_before:.0f} → {rss_after_load:.0f} MB")

    # Warmup on first available clip.
    first_wav = _audio_path(audio_dir, utterances[0]["id"])
    for _ in range(warmup_runs):
        _ = backend.transcribe(first_wav)

    per_utt: list[dict[str, Any]] = []
    for utt in utterances:
        wav = _audio_path(audio_dir, utt["id"])
        if not wav.exists():
            raise FileNotFoundError(
                f"Missing fixture {wav}. Run: python scripts/generate_fixtures.py"
            )
        latencies: list[float] = []
        resource_peaks: list[dict[str, float]] = []
        hypothesis = ""
        for run_i in range(timed_runs):
            with measure_inference(sample_resources=sample_resources):
                hypothesis = backend.transcribe(wav)
            m = last_measurement()
            latencies.append(float(m["latency_s"]))
            resource_peaks.append(m.get("resources") or {})
            print(
                f"  [{utt['id']}] run {run_i + 1}/{timed_runs}: "
                f"{latencies[-1]:.3f}s → {hypothesis[:80]!r}"
            )

        wer = compute_wer(utt["text"], hypothesis)
        inv = invoice_recall(utt.get("invoice_ids") or [], hypothesis)
        per_utt.append(
            {
                "id": utt["id"],
                "category": utt.get("category"),
                "reference": utt["text"],
                "hypothesis": hypothesis,
                "wer": round(wer, 4),
                "invoice": inv,
                "latency_s_runs": [round(x, 4) for x in latencies],
                "latency_s_mean": round(statistics.mean(latencies), 4),
                "latency_s_stdev": round(statistics.pstdev(latencies), 4) if len(latencies) > 1 else 0.0,
                "resources_mean": {
                    "rss_mb_peak_mean": round(
                        statistics.mean(r.get("rss_mb_peak", 0.0) for r in resource_peaks), 1
                    ),
                    "cpu_percent_peak_mean": round(
                        statistics.mean(r.get("cpu_percent_peak", 0.0) for r in resource_peaks), 1
                    ),
                },
            }
        )

    wers = [u["wer"] for u in per_utt]
    lats = [u["latency_s_mean"] for u in per_utt]
    invoice_rows = [u["invoice"] for u in per_utt if u["invoice"].get("applicable")]
    invoice_hit = (
        statistics.mean(r["hit_rate"] for r in invoice_rows if r["hit_rate"] is not None)
        if invoice_rows
        else None
    )

    summary = {
        "model_id": model_cfg["id"],
        "display_name": model_cfg["display_name"],
        "notes": model_cfg.get("notes"),
        "load_s": round(load_s, 3),
        "rss_mb_before_load": round(rss_before, 1),
        "rss_mb_after_load": round(rss_after_load, 1),
        "rss_mb_delta": round(rss_after_load - rss_before, 1),
        "wer_mean": round(statistics.mean(wers), 4),
        "wer_median": round(statistics.median(wers), 4),
        "latency_s_mean": round(statistics.mean(lats), 4),
        "latency_s_median": round(statistics.median(lats), 4),
        "invoice_id_hit_rate_mean": None if invoice_hit is None else round(invoice_hit, 4),
        "utterances": per_utt,
        "quantization": getattr(backend, "quantization", None),
    }

    backend.unload_hint()
    gc.collect()
    return summary


def write_outputs(report: dict[str, Any], cfg: dict[str, Any]) -> None:
    results_dir = ROOT / cfg["outputs"]["results_dir"]
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = ROOT / cfg["outputs"]["stt_json"]
    csv_path = ROOT / cfg["outputs"]["stt_csv"]
    json_path.write_text(json.dumps(report, indent=2) + "\n")

    rows: list[dict[str, Any]] = []
    for model in report["models"]:
        for utt in model["utterances"]:
            rows.append(
                {
                    "model_id": model["model_id"],
                    "display_name": model["display_name"],
                    "utterance_id": utt["id"],
                    "category": utt["category"],
                    "wer": utt["wer"],
                    "latency_s_mean": utt["latency_s_mean"],
                    "invoice_hit_rate": utt["invoice"].get("hit_rate"),
                    "hypothesis": utt["hypothesis"],
                    "reference": utt["reference"],
                }
            )
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "model_id",
                "display_name",
                "utterance_id",
                "category",
                "wer",
                "latency_s_mean",
                "invoice_hit_rate",
                "hypothesis",
                "reference",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {json_path}")
    print(f"Wrote {csv_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "benchmark.yaml",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="Optional subset of model ids from the config.",
    )
    args = parser.parse_args()

    cfg = _load_config(args.config)
    manifest = _load_manifest(ROOT / cfg["fixtures"]["manifest"])
    audio_dir = ROOT / cfg["fixtures"]["audio_dir"]
    model_cfgs = cfg["stt_models"]
    if args.models:
        wanted = set(args.models)
        model_cfgs = [m for m in model_cfgs if m["id"] in wanted]
        missing = wanted - {m["id"] for m in model_cfgs}
        if missing:
            raise SystemExit(f"Unknown model ids: {sorted(missing)}")

    report: dict[str, Any] = {
        "suite": "loopp-stt-benchmark",
        "device_label": cfg.get("device_label"),
        "host": _host_info(),
        "config": {
            "warmup_runs": cfg.get("warmup_runs", 1),
            "timed_runs": cfg.get("timed_runs", 3),
            "sample_rate": cfg.get("sample_rate", 16000),
            "random_seed": cfg.get("random_seed", 42),
            "fixture_engine_note": "Synthetic speech from macOS say / espeak; not real callers.",
        },
        "models": [],
    }

    for model_cfg in model_cfgs:
        summary = evaluate_model(
            model_cfg,
            manifest["utterances"],
            audio_dir,
            warmup_runs=int(cfg.get("warmup_runs", 1)),
            timed_runs=int(cfg.get("timed_runs", 3)),
            sample_resources=bool(cfg.get("resources", {}).get("sample_cpu_during_infer", True)),
        )
        report["models"].append(summary)

    write_outputs(report, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
