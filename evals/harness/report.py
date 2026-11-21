from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.env import EVALS_ROOT
from harness.schema import ScenarioResult


def _serialize_result(result: ScenarioResult) -> dict[str, Any]:
    return {
        "scenario_id": result.scenario_id,
        "name": result.name,
        "kind": result.kind,
        "status": result.status,
        "expected_behavior": result.expected_behavior,
        "actual_behavior": result.actual_behavior,
        "failure_explanation": result.failure_explanation,
        "tool_trace": result.tool_trace,
        "timings_ms": result.timings_ms,
        "judge": result.judge,
        "artifacts_dir": result.artifacts_dir,
        "used_real": result.used_real,
        "turns": [
            {
                "user_text": t.user_text,
                "transcript": t.transcript,
                "assistant_text": t.assistant_text,
                "assertions": [asdict(a) for a in t.assertions],
                "timings_ms": t.timings_ms,
                "tts_bytes": t.tts_bytes,
                "error": t.error,
                "passed": t.passed,
            }
            for t in result.turns
        ],
        "debug": {
            k: v
            for k, v in (result.debug or {}).items()
            if k != "snapshot"  # snapshot kept in failure artifact only
        },
    }


def write_failure_artifact(result: ScenarioResult) -> Path | None:
    if result.status == "PASS":
        return None
    root = EVALS_ROOT / "failures" / "_runs" / result.scenario_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "failure.json"
    payload = _serialize_result(result)
    payload["debug_full"] = result.debug
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def write_report(
    results: list[ScenarioResult],
    *,
    suite: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    latest_dir = EVALS_ROOT / "results" / "latest"
    history_dir = EVALS_ROOT / "results" / "history"
    latest_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    errored = sum(1 for r in results if r.status == "ERROR")
    skipped = sum(1 for r in results if r.status == "SKIP")

    comparisons: list[dict[str, Any]] = []
    if previous:
        prev_map = {r["scenario_id"]: r for r in previous.get("scenarios", [])}
        for r in results:
            old = prev_map.get(r.scenario_id)
            if not old:
                comparisons.append({"scenario_id": r.scenario_id, "change": "new", "status": r.status})
            elif old.get("status") != r.status:
                comparisons.append(
                    {
                        "scenario_id": r.scenario_id,
                        "change": f"{old.get('status')}->{r.status}",
                        "status": r.status,
                    }
                )

    report = {
        "suite": suite,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "errored": errored,
            "skipped": skipped,
        },
        "scenarios": [_serialize_result(r) for r in results],
        "comparison_with_previous": comparisons,
        "real_pipeline_usage": {
            "scenarios_with_real_llm": [
                r.scenario_id for r in results if r.used_real.get("llm") not in {False, None, "mock"}
            ],
            "scenarios_with_real_stt": [
                r.scenario_id for r in results if r.used_real.get("stt") not in {False, None}
            ],
            "scenarios_with_real_tts": [
                r.scenario_id for r in results if r.used_real.get("tts") not in {False, None}
            ],
        },
    }

    for r in results:
        write_failure_artifact(r)

    (latest_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (history_dir / f"report_{stamp}.json").write_text(json.dumps(report, indent=2, default=str))
    (latest_dir / "SUMMARY.md").write_text(_markdown_summary(report))
    return report


def load_previous_report() -> dict[str, Any] | None:
    path = EVALS_ROOT / "results" / "latest" / "report.json"
    if not path.exists():
        return None
    # Move aside conceptually: caller should load before overwrite
    return json.loads(path.read_text())


def _markdown_summary(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"# Loopp evals report ({report['suite']})",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"**{s['passed']} passed** · {s['failed']} failed · {s['errored']} errored · {s['skipped']} skipped · {s['total']} total",
        "",
        "| Scenario | Kind | Status | Expected | Failure |",
        "|---|---|---|---|---|",
    ]
    for sc in report["scenarios"]:
        fail = (sc.get("failure_explanation") or "").replace("|", "/")[:120]
        expected = (sc.get("expected_behavior") or "").replace("|", "/")[:80]
        lines.append(
            f"| `{sc['scenario_id']}` | {sc['kind']} | **{sc['status']}** | {expected} | {fail} |"
        )

    if report.get("comparison_with_previous"):
        lines.extend(["", "## Changes vs previous run", ""])
        for c in report["comparison_with_previous"]:
            lines.append(f"- `{c['scenario_id']}`: {c['change']}")

    lines.extend(
        [
            "",
            "## Real pipeline coverage",
            "",
            f"- Real LLM: {', '.join(report['real_pipeline_usage']['scenarios_with_real_llm']) or 'none'}",
            f"- Real STT: {', '.join(report['real_pipeline_usage']['scenarios_with_real_stt']) or 'none'}",
            f"- Real TTS: {', '.join(report['real_pipeline_usage']['scenarios_with_real_tts']) or 'none'}",
            "",
        ]
    )
    return "\n".join(lines)
