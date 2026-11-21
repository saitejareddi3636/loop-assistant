from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from harness.env import EVALS_ROOT
from harness.schema import Expectation, JudgeSpec, Scenario, Turn


def _expect(data: dict[str, Any] | None) -> Expectation:
    data = data or {}
    return Expectation(
        tools_include=list(data.get("tools_include") or []),
        tools_exclude=list(data.get("tools_exclude") or []),
        tool_completed=list(data.get("tool_completed") or []),
        tool_failed=list(data.get("tool_failed") or []),
        response_contains_any=list(data.get("response_contains_any") or []),
        response_contains_all=list(data.get("response_contains_all") or []),
        response_not_contains=list(data.get("response_not_contains") or []),
        response_regex=list(data.get("response_regex") or []),
        tool_args=dict(data.get("tool_args") or {}),
        receipt_exists=data.get("receipt_exists"),
        receipt_count=data.get("receipt_count"),
        ticket_created=data.get("ticket_created"),
        stt_contains_any=list(data.get("stt_contains_any") or []),
        tts_min_bytes=data.get("tts_min_bytes"),
        max_latency_ms=dict(data.get("max_latency_ms") or {}),
        barge_in_stopped=data.get("barge_in_stopped"),
    )


def load_scenario(path: Path) -> Scenario:
    raw = yaml.safe_load(path.read_text())
    turns = [
        Turn(
            user=t.get("user", ""),
            expect=_expect(t.get("expect")),
            audio_fixture=t.get("audio_fixture"),
            inject_transcript=t.get("inject_transcript"),
        )
        for t in (raw.get("turns") or [])
    ]
    judge_raw = raw.get("judge") or {}
    return Scenario(
        id=raw["id"],
        name=raw.get("name") or raw["id"],
        kind=raw["kind"],
        description=raw.get("description") or "",
        customer_id=raw.get("customer_id") or "cust_pro_001",
        channel=raw.get("channel") or "chat",
        tags=list(raw.get("tags") or []),
        turns=turns,
        expect=_expect(raw.get("expect")),
        tools_script=list(raw.get("tools_script") or []),
        judge=JudgeSpec(
            enabled=bool(judge_raw.get("enabled", False)),
            criteria=list(judge_raw.get("criteria") or ["relevance", "groundedness", "safety"]),
        ),
        expected_behavior=raw.get("expected_behavior") or "",
    )


def load_scenarios(
    *,
    kinds: list[str] | None = None,
    scenario_ids: list[str] | None = None,
) -> list[Scenario]:
    root = EVALS_ROOT / "scenarios"
    scenarios: list[Scenario] = []
    for path in sorted(root.glob("*.yaml")):
        scenario = load_scenario(path)
        if kinds and scenario.kind not in kinds:
            continue
        if scenario_ids and scenario.id not in scenario_ids:
            continue
        scenarios.append(scenario)
    return scenarios
