#!/usr/bin/env python3
"""Build results/SUMMARY.md from measured STT/TTS JSON (no fabricated numbers)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stt", type=Path, default=ROOT / "results" / "stt_results.json")
    parser.add_argument("--tts", type=Path, default=ROOT / "results" / "tts_results.json")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "SUMMARY.md")
    args = parser.parse_args()

    if not args.stt.exists() or not args.tts.exists():
        raise SystemExit("Need both stt_results.json and tts_results.json before summarizing.")

    stt = json.loads(args.stt.read_text())
    tts = json.loads(args.tts.read_text())
    host = stt.get("host", {})
    lines: list[str] = []
    lines.append("# Loopp voice benchmark summary")
    lines.append("")
    lines.append("Evidence-only report generated from measured JSON artifacts.")
    lines.append("")
    lines.append("## Host")
    lines.append("")
    lines.append(f"- Label: `{stt.get('device_label')}`")
    lines.append(
        f"- System: {host.get('system')} {host.get('release')} ({host.get('machine')})"
    )
    lines.append(f"- RAM: {host.get('ram_total_gb')} GB · CPUs: {host.get('cpu_count_logical')}")
    lines.append(f"- Python: {host.get('python')}")
    lines.append(f"- Timestamp (UTC): {host.get('timestamp_utc')}")
    lines.append("")
    lines.append("## STT comparison")
    lines.append("")
    lines.append(
        "| Model | Mean WER | Mean latency (s) | Invoice ID hit-rate | RSS after load (MB) | Load (s) |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    for m in stt["models"]:
        lines.append(
            f"| {m['display_name']} | {m['wer_mean']:.4f} | {m['latency_s_mean']:.3f} | "
            f"{_pct(m.get('invoice_id_hit_rate_mean'))} | {m['rss_mb_after_load']:.0f} | "
            f"{m['load_s']:.2f} |"
        )
    lines.append("")
    lines.append("### Per-utterance WER (last timed hypothesis)")
    lines.append("")
    # Compact matrix
    header = "| Utterance | " + " | ".join(m["model_id"] for m in stt["models"]) + " |"
    sep = "|---|" + "|".join(["---:" for _ in stt["models"]]) + "|"
    lines.append(header)
    lines.append(sep)
    utt_ids = [u["id"] for u in stt["models"][0]["utterances"]]
    by_model = {
        m["model_id"]: {u["id"]: u for u in m["utterances"]} for m in stt["models"]
    }
    for uid in utt_ids:
        cells = [f"{by_model[m['model_id']][uid]['wer']:.3f}" for m in stt["models"]]
        lines.append(f"| `{uid}` | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Pocket TTS")
    lines.append("")
    tm = tts["models"][0]
    lines.append(
        f"- Voice: `{tm['voice']}` · sample rate: {tm['sample_rate']} Hz · load: {tm['load_s']:.2f}s"
    )
    lines.append(
        f"- Mean first-audio: **{tm['first_audio_s_mean']:.3f}s** · mean total: {tm['total_s_mean']:.3f}s"
    )
    lines.append(
        f"- Pass first-audio < 0.5s: `{tm['pass_first_audio_lt_0_5s']}` · RSS after load: {tm['rss_mb_after_load']:.0f} MB"
    )
    lines.append("")
    lines.append("| Utterance | First audio (s) | Total (s) | Audio duration (s) | RTF |")
    lines.append("|---|---:|---:|---:|---:|")
    for i, u in enumerate(tm["utterances"]):
        rtf = u.get("realtime_factor_mean")
        rtf_s = "n/a" if rtf is None else f"{rtf:.2f}"
        preview = u["text"][:48] + ("…" if len(u["text"]) > 48 else "")
        lines.append(
            f"| {i}: {preview} | {u['first_audio_s_mean']:.3f} | {u['total_s_mean']:.3f} | "
            f"{u['audio_duration_s_mean']:.2f} | {rtf_s} |"
        )
    lines.append("")
    lines.append("## Charts")
    lines.append("")
    lines.append("- `charts/stt_comparison.png` — WER, latency, invoice hit-rate")
    lines.append("- `charts/stt_rss.png` — RSS after load")
    lines.append("- `charts/tts_pocket.png` — Pocket TTS first-audio vs total")
    lines.append("")
    lines.append("## Limitations (apply to these numbers)")
    lines.append("")
    lines.append(
        "- Fixtures are **synthetic** (`say` / `espeak`), not production caller audio."
    )
    lines.append(
        "- STT models were evaluated **sequentially** in one process; RSS deltas are indicative, not a clean multi-process isolation."
    )
    lines.append(
        "- Moonshine Streaming Medium used an **offline full-utterance** path (not chunked streaming latency)."
    )
    lines.append(
        "- Invoice hit-rate rewards any accepted orthography of `INV-####`; spoken letter/digit forms are normalized in `metrics.py`."
    )
    lines.append("")

    args.out.write_text("\n".join(lines) + "\n")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
