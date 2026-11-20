#!/usr/bin/env python3
"""One-command Loopp regression runner.

Examples:
  python scripts/run_evals.py --suite deterministic
  python scripts/run_evals.py --suite live --only refund_confirm_live
  python scripts/run_evals.py --suite voice
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

EVALS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVALS_ROOT))

import yaml

from harness.env import bootstrap_evals_env
from harness.loader import load_scenarios
from harness.report import load_previous_report, write_report
from harness.schema import ScenarioResult


def _suite_kinds(suite: str) -> list[str]:
    cfg = yaml.safe_load((EVALS_ROOT / "configs" / "eval.yaml").read_text())
    entry = (cfg.get("suites") or {}).get(suite)
    if not entry:
        raise SystemExit(f"Unknown suite {suite!r}. Choose: {list((cfg.get('suites') or {}))}")
    return list(entry["kinds"])


async def _run_one(session, scenario) -> ScenarioResult:
    from harness.agent_runner import run_agent_scenario
    from harness.tools_runner import run_tools_scenario
    from harness.voice_runner import run_voice_live_scenario, run_voice_sim_scenario

    if scenario.kind == "tools":
        return await run_tools_scenario(session, scenario)
    if scenario.kind == "agent_mock":
        return await run_agent_scenario(session, scenario, real_llm=False)
    if scenario.kind == "agent_live":
        return await run_agent_scenario(session, scenario, real_llm=True)
    if scenario.kind == "voice_live":
        return await run_voice_live_scenario(session, scenario)
    if scenario.kind == "voice_sim":
        return await run_voice_sim_scenario(session, scenario)
    return ScenarioResult(
        scenario_id=scenario.id,
        name=scenario.name,
        kind=scenario.kind,
        status="SKIP",
        expected_behavior=scenario.expected_behavior,
        actual_behavior="",
        failure_explanation=f"Unsupported kind {scenario.kind}",
    )


async def main_async(args: argparse.Namespace) -> int:
    bootstrap_evals_env(suite=args.suite)
    # Import app-bound modules only after env bootstrap.
    from harness.cleanup import reset_mutable_eval_state
    from harness.db import evals_session, prepare_evals_database
    from harness.debug import suggest_fix
    from harness.judge import evaluate_semantic

    kinds = _suite_kinds(args.suite)
    only = args.only.split(",") if args.only else None
    scenarios = load_scenarios(kinds=kinds, scenario_ids=only)
    if not scenarios:
        print("No scenarios matched.", file=sys.stderr)
        return 2

    import os

    print(
        f"Suite={args.suite} kinds={kinds} scenarios={len(scenarios)} "
        f"LLM_PROVIDER={os.environ.get('LLM_PROVIDER')} LLM_MODEL={os.environ.get('LLM_MODEL')}"
    )
    await prepare_evals_database()
    previous = load_previous_report() if args.compare else None

    results: list[ScenarioResult] = []
    async with evals_session() as session:
        pause = float(os.environ.get("EVALS_LIVE_PAUSE_SECONDS", "0") or 0)
        for idx, scenario in enumerate(scenarios):
            if idx and pause > 0 and scenario.kind in {"agent_live", "voice_live"}:
                print(f"  (rate-limit pause {pause:.0f}s)", flush=True)
                await asyncio.sleep(pause)
            print(f"→ {scenario.id} ({scenario.kind}) ...", flush=True)
            await reset_mutable_eval_state(session)
            result = await _run_one(session, scenario)
            if result.status != "PASS" and result.status != "SKIP":
                suggest_fix(result)
            # Skip AI judge when deterministic assertions already failed or rate-limited.
            rate_limited = "rate" in (result.failure_explanation or "").lower() or "429" in (
                result.actual_behavior or ""
            )
            if (
                scenario.judge.enabled
                and result.status == "PASS"
                and not rate_limited
                and os.environ.get("EVALS_DISABLE_JUDGE", "").lower() not in {"1", "true"}
            ):
                result.judge = await evaluate_semantic(scenario, result)
                if result.judge and result.judge.get("pass") is False and not result.judge.get("skipped"):
                    result.status = "FAIL"
                    result.failure_explanation = (
                        (result.failure_explanation + "; " if result.failure_explanation else "")
                        + f"judge: {result.judge.get('rationale', 'failed')}"
                    )
            print(f"  {result.status}", flush=True)
            results.append(result)

    report = write_report(results, suite=args.suite, previous=previous)
    s = report["summary"]
    print(
        f"\nDone: {s['passed']} passed / {s['failed']} failed / "
        f"{s['errored']} errored / {s['skipped']} skipped "
        f"(total {s['total']})"
    )
    print(f"Report: {EVALS_ROOT / 'results' / 'latest' / 'SUMMARY.md'}")
    return 0 if s["failed"] == 0 and s["errored"] == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Loopp regression evals")
    parser.add_argument(
        "--suite",
        default="deterministic",
        choices=["deterministic", "live", "voice", "all"],
    )
    parser.add_argument("--only", default=None, help="Comma-separated scenario ids")
    parser.add_argument("--compare", action="store_true", default=True)
    parser.add_argument("--no-compare", action="store_false", dest="compare")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
