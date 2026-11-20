from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.env import EVALS_ROOT
from harness.schema import ScenarioResult


def suggest_fix(result: ScenarioResult) -> dict[str, Any]:
    """Heuristic root-cause hints for failed scenarios (no auto-deploy)."""
    hints: list[str] = []
    failed_asserts = [
        a
        for t in result.turns
        for a in t.assertions
        if not a.passed
    ]
    names = {a.name for a in failed_asserts}
    text = " ".join(t.assistant_text for t in result.turns).lower()
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in result.tool_trace
        if str(e.get("event_type", "")).startswith("tool.")
    ]

    if "tools_include" in names and "issue_mock_refund" in str(failed_asserts):
        hints.append(
            "Refund tool not called — check confirmation phrasing and Mock/LLM tool-calling path in "
            "api/app/agent/mock_llm.py or live system prompt in api/app/agent/tools.py."
        )
    if "tool_args.issue_mock_refund" in names:
        hints.append(
            "Refund called with wrong args — server requires confirmed=true and matching invoice_id; "
            "inspect planner tool_calls and IssueRefundArgs."
        )
    if "receipt_exists" in names:
        hints.append(
            "Receipt missing — verify issue_mock_refund completed and MockReceipt write in "
            "api/app/domain/refunds.py; ensure evals DB is isolated and seeded."
        )
    if "ticket_created" in names:
        hints.append(
            "Escalation ticket missing — agent should call create_ticket on out-of-scope / Basic tier; "
            "check search_policy should_escalate and create_ticket tool."
        )
    if "stt_contains_any" in names:
        hints.append(
            "STT transcript missed expected tokens — regenerate fixtures with macOS `say`, "
            "or check Moonshine Tiny quality on this utterance; do not loosen invoice assertions."
        )
    if "tts_min_bytes" in names:
        hints.append(
            "TTS produced too little audio — Pocket TTS/NullTTS backend issue; check VOICE_BACKEND=local "
            "and pocket_tts adapter."
        )
    if "response_contains_any" in names and "pro-bill" in str(failed_asserts).lower():
        hints.append(
            "Missing policy citation — RAG/search_policy may be empty; re-seed with seed_policy_index "
            "and verify EMBEDDING_PROVIDER=hash on evals DB."
        )
    if "prompt" in result.scenario_id or "injection" in result.scenario_id:
        hints.append(
            "Prompt-injection scenario failed — agent must refuse unsafe refunds; strengthen SYSTEM_PROMPT "
            "rules and keep confirmed=false enforcement in tools."
        )
    if not hints:
        hints.append(
            "Inspect failure.json tool_trace + snapshot; reproduce with "
            f"`python scripts/run_evals.py --suite {result.kind} --only {result.scenario_id}`."
        )

    suggestion = {
        "scenario_id": result.scenario_id,
        "status": result.status,
        "failed_assertions": [a.__dict__ for a in failed_asserts],
        "likely_root_causes": hints,
        "suggested_fix_steps": [
            "Reproduce on branch feat/evals-regression-framework (or a new fix branch).",
            "Apply a targeted change under api/app/ only if production behavior is wrong.",
            "Never edit golden expectations solely to force a pass.",
            "Rerun failed scenario, then full deterministic suite.",
            "Do not auto-deploy or restart Oracle.",
        ],
        "tools_seen": tools,
        "response_excerpt": text[:400],
    }

    out = EVALS_ROOT / "failures" / "_runs" / result.scenario_id / "debug_suggestion.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(suggestion, indent=2))
    return suggestion


def load_failure(scenario_id: str) -> dict[str, Any] | None:
    path = EVALS_ROOT / "failures" / "_runs" / scenario_id / "failure.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())
