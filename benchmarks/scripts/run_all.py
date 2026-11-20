#!/usr/bin/env python3
"""Orchestrate fixture generation → STT → TTS → charts → SUMMARY.md."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-fixtures", action="store_true")
    parser.add_argument("--skip-stt", action="store_true")
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--models", nargs="*", default=None)
    args = parser.parse_args()

    if not args.skip_fixtures:
        run([PY, "scripts/generate_fixtures.py"])
    if not args.skip_stt:
        cmd = [PY, "scripts/run_stt_benchmark.py"]
        if args.models:
            cmd += ["--models", *args.models]
        run(cmd)
    if not args.skip_tts:
        run([PY, "scripts/run_tts_benchmark.py"])
    run([PY, "scripts/plot_results.py"])
    run([PY, "scripts/write_summary.py"])
    print("\nBenchmark suite complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
