from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import run_agent_turn
from app.db.models import AgentRun, Conversation, Message
from app.events.bus import EventBus
from harness.assertions import check_expectation
from harness.schema import Scenario, ScenarioResult, TurnResult
from harness.traces import conversation_snapshot, load_tool_events


async def _ensure_conversation(session: AsyncSession, customer_id: str, title: str) -> Conversation:
    conversation = Conversation(customer_id=customer_id, title=title)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def run_agent_scenario(
    session: AsyncSession,
    scenario: Scenario,
    *,
    source: str = "chat",
    real_llm: bool = False,
) -> ScenarioResult:
    bus = EventBus()
    conversation = await _ensure_conversation(session, scenario.customer_id, f"eval:{scenario.id}")
    turn_results: list[TurnResult] = []
    all_events: list[dict[str, Any]] = []
    t_suite = time.perf_counter()

    try:
        for turn in scenario.turns:
            run_id = uuid.uuid4()
            client_turn_id = str(uuid.uuid4())
            session.add(
                AgentRun(
                    id=run_id,
                    conversation_id=conversation.id,
                    client_turn_id=client_turn_id,
                    status="running",
                )
            )
            session.add(
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content=turn.user,
                    client_turn_id=client_turn_id,
                    run_id=run_id,
                    meta={"source": source, "eval_scenario": scenario.id},
                )
            )
            await session.commit()

            t0 = time.perf_counter()
            reply = await run_agent_turn(
                session,
                bus,
                conversation_id=conversation.id,
                run_id=run_id,
                customer_id=scenario.customer_id,
                user_text=turn.user,
                source=source,
                extra_metrics={"eval_scenario": scenario.id},
            )
            agent_ms = (time.perf_counter() - t0) * 1000

            events = await load_tool_events(session, conversation.id)
            # Only events for this run for tool assertions (still keep full trace)
            run_events = [e for e in events if e.get("run_id") == str(run_id)]
            assertions = await check_expectation(
                session,
                turn.expect,
                response=reply,
                events=run_events,
                conversation_id=conversation.id,
                timings_ms={"agent_turn": agent_ms},
            )
            turn_results.append(
                TurnResult(
                    user_text=turn.user,
                    transcript=None,
                    assistant_text=reply,
                    tool_events=run_events,
                    assertions=assertions,
                    timings_ms={"agent_turn": agent_ms},
                )
            )
            all_events = events

        snap = await conversation_snapshot(session, conversation.id)
        failed = [tr for tr in turn_results if not tr.passed]
        status = "PASS" if not failed else "FAIL"
        actual = turn_results[-1].assistant_text if turn_results else ""
        explanation = ""
        if failed:
            bits = []
            for tr in failed:
                for a in tr.assertions:
                    if not a.passed:
                        bits.append(f"{a.name}: {a.detail}")
            explanation = "; ".join(bits)

        return ScenarioResult(
            scenario_id=scenario.id,
            name=scenario.name,
            kind=scenario.kind,
            status=status,
            expected_behavior=scenario.expected_behavior or scenario.description,
            actual_behavior=actual[:500],
            failure_explanation=explanation,
            turns=turn_results,
            tool_trace=all_events,
            timings_ms={"scenario_total": (time.perf_counter() - t_suite) * 1000},
            used_real={
                "stt": False,
                "llm": real_llm,
                "tools": True,
                "rag": True,
                "tts": False,
            },
            debug={"snapshot": snap, "conversation_id": str(conversation.id)},
        )
    except Exception as exc:  # noqa: BLE001
        return ScenarioResult(
            scenario_id=scenario.id,
            name=scenario.name,
            kind=scenario.kind,
            status="ERROR",
            expected_behavior=scenario.expected_behavior or scenario.description,
            actual_behavior="",
            failure_explanation=str(exc),
            turns=turn_results,
            tool_trace=all_events,
            used_real={"stt": False, "llm": real_llm, "tools": True, "rag": True, "tts": False},
            debug={"error": repr(exc)},
        )
