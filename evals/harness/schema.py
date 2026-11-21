from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["tools", "agent_mock", "agent_live", "voice_live", "voice_sim"]
Status = Literal["PASS", "FAIL", "SKIP", "ERROR"]


@dataclass
class Expectation:
    tools_include: list[str] = field(default_factory=list)
    tools_exclude: list[str] = field(default_factory=list)
    tool_completed: list[str] = field(default_factory=list)
    tool_failed: list[str] = field(default_factory=list)
    response_contains_any: list[str] = field(default_factory=list)
    response_contains_all: list[str] = field(default_factory=list)
    response_not_contains: list[str] = field(default_factory=list)
    response_regex: list[str] = field(default_factory=list)
    tool_args: dict[str, dict[str, Any]] = field(default_factory=dict)
    receipt_exists: dict[str, Any] | None = None
    receipt_count: dict[str, Any] | None = None
    ticket_created: bool | None = None
    stt_contains_any: list[str] = field(default_factory=list)
    tts_min_bytes: int | None = None
    max_latency_ms: dict[str, float] = field(default_factory=dict)
    barge_in_stopped: bool | None = None


@dataclass
class Turn:
    user: str
    expect: Expectation = field(default_factory=Expectation)
    audio_fixture: str | None = None
    inject_transcript: str | None = None  # bypass STT when set in voice_live


@dataclass
class JudgeSpec:
    enabled: bool = False
    criteria: list[str] = field(default_factory=lambda: ["relevance", "groundedness", "safety"])


@dataclass
class Scenario:
    id: str
    name: str
    kind: Kind
    description: str
    customer_id: str = "cust_pro_001"
    channel: str = "chat"
    tags: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    expect: Expectation = field(default_factory=Expectation)  # scenario-level (tools)
    tools_script: list[dict[str, Any]] = field(default_factory=list)
    judge: JudgeSpec = field(default_factory=JudgeSpec)
    expected_behavior: str = ""


@dataclass
class AssertionResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class TurnResult:
    user_text: str
    transcript: str | None
    assistant_text: str
    tool_events: list[dict[str, Any]]
    assertions: list[AssertionResult]
    timings_ms: dict[str, float] = field(default_factory=dict)
    tts_bytes: int = 0
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(a.passed for a in self.assertions)


@dataclass
class ScenarioResult:
    scenario_id: str
    name: str
    kind: Kind
    status: Status
    expected_behavior: str
    actual_behavior: str
    failure_explanation: str = ""
    turns: list[TurnResult] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    judge: dict[str, Any] | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    artifacts_dir: str | None = None
    used_real: dict[str, bool] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"
