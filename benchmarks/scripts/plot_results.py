#!/usr/bin/env python3
"""Render comparison charts from STT/TTS result JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _bar(ax, labels: list[str], values: list[float], title: str, ylabel: str) -> None:
    colors = ["#1f4e5f", "#2d6a4f", "#bc4749", "#e09f3e"]
    bars = ax.bar(labels, values, color=colors[: len(labels)])
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=15)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{val:.3f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )


def plot_stt(stt_path: Path, charts_dir: Path) -> None:
    data = json.loads(stt_path.read_text())
    models = data["models"]
    labels = [m["display_name"].replace(" (ONNX)", "").replace(" (ONNX INT8)", "") for m in models]
    short = []
    for lab in labels:
        if "Tiny" in lab:
            short.append("Moonshine Tiny")
        elif "Streaming" in lab or "Medium" in lab:
            short.append("Moonshine Med")
        elif "Parakeet" in lab:
            short.append("Parakeet 0.6B")
        else:
            short.append(lab[:18])

    charts_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    _bar(axes[0], short, [m["wer_mean"] for m in models], "Mean WER (lower better)", "WER")
    _bar(
        axes[1],
        short,
        [m["latency_s_mean"] for m in models],
        "Mean latency / utterance",
        "Seconds",
    )
    inv = [
        (m["invoice_id_hit_rate_mean"] if m["invoice_id_hit_rate_mean"] is not None else 0.0)
        for m in models
    ]
    _bar(axes[2], short, inv, "Invoice ID hit-rate", "Hit rate")
    fig.suptitle("Loopp STT comparison (synthetic billing utterances)", fontsize=12)
    fig.tight_layout()
    out = charts_dir / "stt_comparison.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"Wrote {out}")

    # Resource chart
    fig, ax = plt.subplots(figsize=(7, 4))
    _bar(
        ax,
        short,
        [m["rss_mb_after_load"] for m in models],
        "RSS after model load",
        "MB",
    )
    fig.tight_layout()
    out = charts_dir / "stt_rss.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"Wrote {out}")


def plot_tts(tts_path: Path, charts_dir: Path) -> None:
    data = json.loads(tts_path.read_text())
    model = data["models"][0]
    charts_dir.mkdir(parents=True, exist_ok=True)
    labels = [f"utt{i}" for i in range(len(model["utterances"]))]
    first = [u["first_audio_s_mean"] for u in model["utterances"]]
    total = [u["total_s_mean"] for u in model["utterances"]]

    fig, ax = plt.subplots(figsize=(7, 4))
    x = range(len(labels))
    ax.bar([i - 0.18 for i in x], first, width=0.36, label="First audio", color="#1f4e5f")
    ax.bar([i + 0.18 for i in x], total, width=0.36, label="Total synth", color="#e09f3e")
    ax.axhline(0.5, color="#bc4749", linestyle="--", linewidth=1, label="0.5s target")
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("Seconds")
    ax.set_title("Pocket TTS latency by utterance")
    ax.legend(fontsize=8)
    fig.tight_layout()
    out = charts_dir / "tts_pocket.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"Wrote {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stt", type=Path, default=ROOT / "results" / "stt_results.json")
    parser.add_argument("--tts", type=Path, default=ROOT / "results" / "tts_results.json")
    parser.add_argument("--charts-dir", type=Path, default=ROOT / "results" / "charts")
    args = parser.parse_args()
    if args.stt.exists():
        plot_stt(args.stt, args.charts_dir)
    else:
        print(f"Skip STT charts — missing {args.stt}")
    if args.tts.exists():
        plot_tts(args.tts, args.charts_dir)
    else:
        print(f"Skip TTS charts — missing {args.tts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
