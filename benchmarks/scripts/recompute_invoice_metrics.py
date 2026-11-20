#!/usr/bin/env python3
"""Recompute invoice hit-rates from existing STT hypotheses (no model reload)."""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from metrics import invoice_recall  # noqa: E402


def main() -> int:
    path = ROOT / "results" / "stt_results.json"
    data = json.loads(path.read_text())
    for model in data["models"]:
        rates = []
        for utt in model["utterances"]:
            inv = invoice_recall(
                # recover expected IDs from prior payload when present
                utt.get("invoice", {}).get("expected")
                or [],
                utt["hypothesis"],
            )
            # If expected was empty in prior payload but category implies invoice, keep prior expected.
            if not inv["applicable"] and utt.get("invoice", {}).get("expected"):
                inv = invoice_recall(utt["invoice"]["expected"], utt["hypothesis"])
            utt["invoice"] = inv
            if inv.get("applicable") and inv.get("hit_rate") is not None:
                rates.append(inv["hit_rate"])
        model["invoice_id_hit_rate_mean"] = (
            round(statistics.mean(rates), 4) if rates else None
        )
        print(
            model["model_id"],
            "invoice_hit_rate",
            model["invoice_id_hit_rate_mean"],
        )
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
