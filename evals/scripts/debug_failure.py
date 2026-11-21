#!/usr/bin/env python3
"""Print failure artifact + suggested fix for a scenario id."""
from __future__ import annotations

import json
import sys
from pathlib import Path

EVALS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVALS_ROOT))

from harness.debug import load_failure


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/debug_failure.py <scenario_id>")
    sid = sys.argv[1]
    failure = load_failure(sid)
    if not failure:
        raise SystemExit(f"No failure artifact for {sid}")
    print(json.dumps(failure, indent=2)[:8000])
    suggestion = EVALS_ROOT / "failures" / "_runs" / sid / "debug_suggestion.json"
    if suggestion.exists():
        print("\n--- suggestion ---\n")
        print(suggestion.read_text())


if __name__ == "__main__":
    main()
