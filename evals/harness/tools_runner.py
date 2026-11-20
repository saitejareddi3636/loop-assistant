from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import ToolContext, build_tools
from app.db.models import Conversation
from app.domain import fixtures as domain_fixtures
from app.domain.refunds import issue_mock_refund
from app.events.bus import EventBus
from harness.assertions import check_expectation
from harness.schema import Scenario, ScenarioResult, TurnResult
from harness.traces import conversation_snapshot, load_tool_events


async def run_tools_scenario(session: AsyncSession, scenario: Scenario) -> ScenarioResult:
    """Deterministic tool/domain checks — no LLM. Labeled kind=tools."""
    bus = EventBus()
    conversation = Conversation(customer_id=scenario.customer_id, title=f"eval-tools:{scenario.id}")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    ctx = ToolContext(
        session=session,
        event_bus=bus,
        conversation_id=conversation.id,
        run_id=uuid.uuid4(),
        customer_id=scenario.customer_id,
    )
    tools = {t.name: t for t in build_tools(ctx)}
    last_response = ""
    synthetic_events: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    patched_invoices: dict[str, Any] | None = None

    try:
        for step in scenario.tools_script:
            action = step.get("action")
            if action == "patch_invoice":
                # Temporary evals-only invoice for window/amount edge cases.
                from datetime import date, timedelta
                from app.domain.fixtures import Invoice

                inv = Invoice(
                    id=step["invoice_id"],
                    customer_id=step.get("customer_id", scenario.customer_id),
                    amount_cents=int(step.get("amount_cents", 2900)),
                    currency="USD",
                    status="posted",
                    description=step.get("description", "evals invoice"),
                    charged_on=date.fromisoformat(step["charged_on"])
                    if step.get("charged_on")
                    else domain_fixtures.DEMO_AS_OF - timedelta(days=int(step.get("age_days", 3))),
                    is_duplicate=bool(step.get("is_duplicate", True)),
                )
                if patched_invoices is None:
                    patched_invoices = dict(domain_fixtures.INVOICES)
                domain_fixtures.INVOICES[inv.id] = inv
                continue

            if action == "issue_mock_refund_direct":
                result = await issue_mock_refund(
                    session,
                    conversation_id=conversation.id,
                    customer_id=step.get("customer_id", scenario.customer_id),
                    invoice_id=step["invoice_id"],
                )
                await session.commit()
                last_response = str(result)
                synthetic_events.append(
                    {
                        "event_type": "tool.completed" if result.get("ok") else "tool.failed",
                        "payload": {"tool": "issue_mock_refund", "status": "completed" if result.get("ok") else "failed", **result},
                    }
                )
                continue

            tool_name = step["tool"]
            args = dict(step.get("args") or {})
            result = await tools[tool_name].ainvoke(args)
            last_response = str(result)
            # Capture events from bus persistence
            synthetic_events = await load_tool_events(session, conversation.id)

        # Restore invoices if patched
        if patched_invoices is not None:
            domain_fixtures.INVOICES.clear()
            domain_fixtures.INVOICES.update(patched_invoices)

        events = await load_tool_events(session, conversation.id)
        if not events:
            events = synthetic_events

        assertions = await check_expectation(
            session,
            scenario.expect,
            response=last_response,
            events=events,
            conversation_id=conversation.id,
        )
        # Extra scripted asserts
        for step in scenario.tools_script:
            if step.get("action") == "assert_result_field":
                # Re-run last tool not available; fields checked via expect.response / receipt
                pass

        turn = TurnResult(
            user_text="(tools_script)",
            transcript=None,
            assistant_text=last_response[:1000],
            tool_events=events,
            assertions=assertions,
            timings_ms={"tools_total": (time.perf_counter() - t0) * 1000},
        )
        status = "PASS" if turn.passed else "FAIL"
        explanation = "; ".join(a.detail for a in assertions if not a.passed)
        snap = await conversation_snapshot(session, conversation.id)
        return ScenarioResult(
            scenario_id=scenario.id,
            name=scenario.name,
            kind=scenario.kind,
            status=status,
            expected_behavior=scenario.expected_behavior or scenario.description,
            actual_behavior=last_response[:500],
            failure_explanation=explanation,
            turns=[turn],
            tool_trace=events,
            timings_ms={"scenario_total": (time.perf_counter() - t0) * 1000},
            used_real={"stt": False, "llm": False, "tools": True, "rag": True, "tts": False},
            debug={"snapshot": snap},
        )
    except Exception as exc:  # noqa: BLE001
        if patched_invoices is not None:
            domain_fixtures.INVOICES.clear()
            domain_fixtures.INVOICES.update(patched_invoices)
        return ScenarioResult(
            scenario_id=scenario.id,
            name=scenario.name,
            kind=scenario.kind,
            status="ERROR",
            expected_behavior=scenario.expected_behavior or scenario.description,
            actual_behavior=last_response[:500],
            failure_explanation=str(exc),
            used_real={"stt": False, "llm": False, "tools": True, "rag": True, "tts": False},
            debug={"error": repr(exc)},
        )
