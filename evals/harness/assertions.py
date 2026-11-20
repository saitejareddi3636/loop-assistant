from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EscalationTicket, MockReceipt
from harness.schema import AssertionResult, Expectation


def _tool_names(events: list[dict[str, Any]], *, status: str | None = None) -> list[str]:
    names: list[str] = []
    for ev in events:
        if ev.get("event_type") not in {"tool.started", "tool.completed", "tool.failed"}:
            continue
        payload = ev.get("payload") or {}
        if status and payload.get("status") != status and not (
            (status == "completed" and ev.get("event_type") == "tool.completed")
            or (status == "failed" and ev.get("event_type") == "tool.failed")
            or (status == "started" and ev.get("event_type") == "tool.started")
        ):
            # Prefer event_type mapping
            if status == "completed" and ev.get("event_type") != "tool.completed":
                continue
            if status == "failed" and ev.get("event_type") != "tool.failed":
                continue
            if status == "started" and ev.get("event_type") != "tool.started":
                continue
        name = payload.get("tool")
        if name:
            names.append(str(name))
    return names


def _tool_args_from_events(events: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    """Best-effort: started events often carry args in detail."""
    for ev in events:
        payload = ev.get("payload") or {}
        if payload.get("tool") != tool:
            continue
        # Started payloads include invoice_id / confirmed / etc.
        return {k: v for k, v in payload.items() if k not in {"tool", "status"}}
    return {}


async def check_expectation(
    session: AsyncSession,
    expect: Expectation,
    *,
    response: str,
    events: list[dict[str, Any]],
    conversation_id: Any = None,
    transcript: str | None = None,
    tts_bytes: int = 0,
    timings_ms: dict[str, float] | None = None,
) -> list[AssertionResult]:
    results: list[AssertionResult] = []
    text = response or ""
    # Normalize curly quotes so "can't" matches model output "can’t".
    text_l = (
        text.lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    timings_ms = timings_ms or {}

    if expect.tools_include:
        seen = set(_tool_names(events))
        missing = [t for t in expect.tools_include if t not in seen]
        results.append(
            AssertionResult(
                "tools_include",
                not missing,
                f"missing={missing}; seen={sorted(seen)}" if missing else "ok",
            )
        )

    if expect.tools_exclude:
        seen = set(_tool_names(events))
        bad = [t for t in expect.tools_exclude if t in seen]
        results.append(
            AssertionResult(
                "tools_exclude",
                not bad,
                f"unexpected={bad}" if bad else "ok",
            )
        )

    if expect.tool_completed:
        done = set(_tool_names(events, status="completed"))
        missing = [t for t in expect.tool_completed if t not in done]
        results.append(
            AssertionResult(
                "tool_completed",
                not missing,
                f"missing={missing}; done={sorted(done)}" if missing else "ok",
            )
        )

    if expect.tool_failed:
        failed = set(_tool_names(events, status="failed"))
        missing = [t for t in expect.tool_failed if t not in failed]
        results.append(
            AssertionResult(
                "tool_failed",
                not missing,
                f"missing={missing}; failed={sorted(failed)}" if missing else "ok",
            )
        )

    for tool, required in (expect.tool_args or {}).items():
        actual = _tool_args_from_events(events, tool)
        mismatches = []
        for key, value in required.items():
            if actual.get(key) != value:
                mismatches.append(f"{key}: expected={value!r} actual={actual.get(key)!r}")
        results.append(
            AssertionResult(
                f"tool_args.{tool}",
                not mismatches,
                "; ".join(mismatches) if mismatches else "ok",
            )
        )

    def _norm(s: str) -> str:
        return s.lower().replace("’", "'").replace("‘", "'")

    if expect.response_contains_any:
        ok = any(_norm(s) in text_l for s in expect.response_contains_any)
        results.append(
            AssertionResult(
                "response_contains_any",
                ok,
                f"need any of {expect.response_contains_any}; got={text[:240]!r}",
            )
        )

    if expect.response_contains_all:
        missing = [s for s in expect.response_contains_all if _norm(s) not in text_l]
        results.append(
            AssertionResult(
                "response_contains_all",
                not missing,
                f"missing={missing}" if missing else "ok",
            )
        )

    if expect.response_not_contains:
        bad = [s for s in expect.response_not_contains if _norm(s) in text_l]
        results.append(
            AssertionResult(
                "response_not_contains",
                not bad,
                f"forbidden present={bad}" if bad else "ok",
            )
        )

    for pattern in expect.response_regex:
        ok = re.search(pattern, text, flags=re.IGNORECASE) is not None
        results.append(AssertionResult(f"response_regex:{pattern}", ok, "ok" if ok else f"no match in {text[:200]!r}"))

    if expect.stt_contains_any:
        tr = (transcript or "").lower()
        ok = any(s.lower() in tr for s in expect.stt_contains_any)
        results.append(
            AssertionResult(
                "stt_contains_any",
                ok,
                f"need any of {expect.stt_contains_any}; transcript={transcript!r}",
            )
        )

    if expect.tts_min_bytes is not None:
        ok = tts_bytes >= expect.tts_min_bytes
        results.append(
            AssertionResult(
                "tts_min_bytes",
                ok,
                f"bytes={tts_bytes} min={expect.tts_min_bytes}",
            )
        )

    for key, limit in (expect.max_latency_ms or {}).items():
        actual = timings_ms.get(key)
        ok = actual is not None and actual <= limit
        results.append(
            AssertionResult(
                f"max_latency_ms.{key}",
                bool(ok),
                f"actual={actual} limit={limit}",
            )
        )

    if expect.receipt_exists:
        cid = expect.receipt_exists.get("customer_id")
        iid = expect.receipt_exists.get("invoice_id")
        row = await session.scalar(
            select(MockReceipt).where(
                MockReceipt.customer_id == cid,
                MockReceipt.invoice_id == iid,
            )
        )
        results.append(
            AssertionResult(
                "receipt_exists",
                row is not None,
                f"customer={cid} invoice={iid} found={row is not None}",
            )
        )

    if expect.receipt_count:
        cid = expect.receipt_count.get("customer_id")
        iid = expect.receipt_count.get("invoice_id")
        expected_n = int(expect.receipt_count.get("count", 1))
        rows = (
            await session.scalars(
                select(MockReceipt).where(
                    MockReceipt.customer_id == cid,
                    MockReceipt.invoice_id == iid,
                )
            )
        ).all()
        results.append(
            AssertionResult(
                "receipt_count",
                len(rows) == expected_n,
                f"expected={expected_n} actual={len(rows)}",
            )
        )

    if expect.ticket_created is not None and conversation_id is not None:
        tickets = (
            await session.scalars(
                select(EscalationTicket).where(EscalationTicket.conversation_id == conversation_id)
            )
        ).all()
        exists = len(tickets) > 0
        results.append(
            AssertionResult(
                "ticket_created",
                exists is bool(expect.ticket_created),
                f"expected={expect.ticket_created} actual={exists} ids={[t.id for t in tickets]}",
            )
        )

    if expect.barge_in_stopped is not None:
        # Caller sets timings_ms['barge_in_stopped']=1.0 on success
        stopped = bool(timings_ms.get("barge_in_stopped"))
        results.append(
            AssertionResult(
                "barge_in_stopped",
                stopped is bool(expect.barge_in_stopped),
                f"expected={expect.barge_in_stopped} actual={stopped}",
            )
        )

    return results
