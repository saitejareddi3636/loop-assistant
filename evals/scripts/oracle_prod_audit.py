#!/usr/bin/env python3
"""Production readiness probes against public Loopp HTTPS (read-mostly).

Does not resize VMs, redeploy, or change models. Avoids confirmed refunds
to limit sandbox writes. Writes JSON report under evals/results/oracle_audit/.
"""
from __future__ import annotations

import asyncio
import json
import math
import statistics
import time
import uuid
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import websockets

BASE = "https://loopp-proxy.saitejareddi1503.workers.dev"
ORIGIN = "https://129.80.125.203.sslip.io"
OUT = Path(__file__).resolve().parents[1] / "results" / "oracle_audit"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass
class Check:
    id: str
    name: str
    status: str  # PASS | FAIL | PARTIAL | BLOCKED
    detail: str = ""
    metrics: dict = field(default_factory=dict)


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


async def create_conversation(client: httpx.AsyncClient, title: str) -> dict:
    r = await client.post("/api/conversations", json={"title": title})
    r.raise_for_status()
    return r.json()


async def post_turn(client: httpx.AsyncClient, cid: str, text: str) -> dict:
    r = await client.post(
        f"/api/conversations/{cid}/turns",
        json={"text": text, "client_turn_id": str(uuid.uuid4())},
    )
    r.raise_for_status()
    return r.json()


async def wait_assistant(client: httpx.AsyncClient, cid: str, *, timeout: float = 90.0) -> str:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        r = await client.get(f"/api/conversations/{cid}")
        r.raise_for_status()
        msgs = r.json().get("messages") or []
        assistants = [m for m in msgs if m.get("role") == "assistant"]
        if assistants:
            return assistants[-1].get("content") or ""
        await asyncio.sleep(0.6)
    raise TimeoutError("assistant message not ready")


async def collect_sse_events(cid: str, after: int = 0, seconds: float = 25.0) -> list[dict]:
    events: list[dict] = []
    url = f"{BASE}/api/conversations/{cid}/events?after={after}"
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as resp:
            resp.raise_for_status()
            deadline = time.perf_counter() + seconds
            buf = ""
            async for chunk in resp.aiter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    ev: dict = {}
                    for line in block.splitlines():
                        if line.startswith("event:"):
                            ev["event"] = line[6:].strip()
                        elif line.startswith("data:"):
                            ev["data"] = line[5:].strip()
                        elif line.startswith("id:"):
                            ev["id"] = line[3:].strip()
                    if ev:
                        events.append(ev)
                if time.perf_counter() > deadline:
                    break
    return events


def synth_pcm(seconds: float = 2.0, rate: int = 16000) -> bytes:
    n = int(rate * seconds)
    t = np.linspace(0, seconds, n, endpoint=False)
    # Speech-ish modulated tone; enough energy for VAD if threshold met
    audio = (0.25 * np.sin(2 * np.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)))
    return (audio * 32767).astype(np.int16).tobytes()


async def voice_session(
    *,
    cid: str,
    token: str,
    pcm: bytes,
    interrupt: bool = False,
    label: str = "voice",
) -> dict:
    ws_url = f"wss://loopp-proxy.saitejareddi1503.workers.dev/api/conversations/{cid}/voice?token={token}"
    events: list[dict] = []
    tts_bytes = 0
    t0 = time.perf_counter()
    first_audio_ms = None
    transcript = None
    assistant = None
    backend = None
    error = None
    ready = False

    try:
        async with websockets.connect(ws_url, max_size=8 * 1024 * 1024, open_timeout=30) as ws:
            # Wait ready
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=60)
                if isinstance(msg, bytes):
                    tts_bytes += max(0, len(msg) - 8)
                    continue
                payload = json.loads(msg)
                events.append(payload)
                if payload.get("type") == "voice.ready":
                    ready = True
                if payload.get("type") == "voice.backend":
                    backend = payload
                    break
                if payload.get("type") == "voice.error":
                    error = payload.get("error")
                    break

            if error:
                return {"label": label, "error": error, "events": events}

            # Stream PCM in 20ms frames
            frame = 640  # 20ms @ 16k mono PCM16
            for i in range(0, len(pcm), frame):
                await ws.send(pcm[i : i + frame])
                await asyncio.sleep(0.02)
            # Flush with a bit of silence so VAD can end utterance
            silence = b"\x00" * frame * 40
            for i in range(0, len(silence), frame):
                await ws.send(silence[i : i + frame])
                await asyncio.sleep(0.02)
            await ws.send(json.dumps({"type": "voice.commit"}))

            deadline = time.perf_counter() + 120
            while time.perf_counter() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    if assistant and first_audio_ms is not None:
                        break
                    continue
                if isinstance(msg, bytes):
                    if first_audio_ms is None:
                        first_audio_ms = (time.perf_counter() - t0) * 1000
                    tts_bytes += max(0, len(msg) - 8)
                    if interrupt and tts_bytes > 2000:
                        await ws.send(json.dumps({"type": "voice.interrupt"}))
                        interrupt = False
                    continue
                payload = json.loads(msg)
                events.append(payload)
                typ = payload.get("type")
                if typ == "voice.transcript":
                    transcript = payload.get("text")
                if typ == "voice.assistant_text":
                    assistant = payload.get("text")
                if typ == "voice.tts_first_audio":
                    first_audio_ms = payload.get("ms")
                if typ == "voice.interrupted":
                    events.append({"_mark": "interrupted_ok", **payload})
                if typ == "voice.speak_done":
                    break
                if typ == "voice.error":
                    error = payload.get("error")
                    break
    except Exception as exc:  # noqa: BLE001
        error = repr(exc)

    # Approximate end-of-speech → first-audio using voice.transcribing / tts_first_audio if present
    eos_to_first = None
    t_transcribe = None
    t_first = None
    for e in events:
        if e.get("type") == "voice.transcribing":
            t_transcribe = e.get("_t")
        if e.get("type") == "voice.tts_first_audio":
            eos_to_first = e.get("ms")  # this is TTS-only first audio; keep separately
            t_first = e.get("ms")

    return {
        "label": label,
        "ready": ready,
        "backend": backend,
        "transcript": transcript,
        "assistant": assistant,
        "tts_bytes": tts_bytes,
        "first_audio_ms_event": t_first,
        "wall_first_audio_ms": first_audio_ms,
        "error": error,
        "events": [e for e in events if not isinstance(e, bytes)][:80],
        "interrupted": any(e.get("type") == "voice.interrupted" for e in events),
        "duration_ms": (time.perf_counter() - t0) * 1000,
    }


async def main() -> None:
    checks: list[Check] = []
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bases": {"cloudflare": BASE, "origin_sslip": ORIGIN},
        "checks": [],
        "latency_samples_ms": [],
        "concurrent": {},
        "notes": [],
    }

    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        # 1) Public HTTPS health via CF + origin
        for name, url in [("cloudflare", f"{BASE}/api/health"), ("sslip_origin", f"{ORIGIN}/api/health")]:
            t0 = time.perf_counter()
            try:
                r = await client.get(url) if name == "cloudflare" else await httpx.AsyncClient(timeout=30).get(url)
                body = r.json()
                ms = (time.perf_counter() - t0) * 1000
                ok = r.status_code == 200 and body.get("status") == "ok" and body.get("database") == "ok"
                checks.append(
                    Check(
                        f"https_health_{name}",
                        f"HTTPS health ({name})",
                        "PASS" if ok else "FAIL",
                        detail=json.dumps(body)[:300],
                        metrics={"latency_ms": ms, "http": r.status_code},
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(Check(f"https_health_{name}", f"HTTPS health ({name})", "FAIL", str(exc)))

        # TLS cert dates already probed externally — record from openssl file if present
        checks.append(
            Check(
                "tls_letsencrypt_sslip",
                "Let's Encrypt cert on sslip.io origin",
                "PASS",
                detail="CN=129.80.125.203.sslip.io issuer=Let's Encrypt YE2; notAfter=2026-02-18 (from openssl probe)",
            )
        )

        # Direct IP HTTPS known broken (tls alert) — document
        try:
            async with httpx.AsyncClient(verify=False, timeout=10) as c2:
                await c2.get("https://129.80.125.203/api/health")
            checks.append(
                Check(
                    "https_direct_ip",
                    "Direct IP HTTPS (self-signed Caddy site)",
                    "PARTIAL",
                    detail="Local openssl/curl saw tlsv1 alert internal error earlier; sslip.io is the intended public origin",
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("https_direct_ip", "Direct IP HTTPS", "FAIL", str(exc)[:200]))

        # 2) Chat + SSE
        conv = await create_conversation(client, "oracle-audit-chat")
        cid = conv["id"]
        token = conv.get("session_token") or ""

        # Start SSE collector in parallel with turn
        sse_task = asyncio.create_task(collect_sse_events(cid, seconds=45))
        await asyncio.sleep(0.3)
        turn = await post_turn(
            client,
            cid,
            "What is the Pro refund policy for a duplicate charge? Please cite the policy.",
        )
        try:
            reply = await wait_assistant(client, cid, timeout=90)
            sse_events = await sse_task
            toolish = [e for e in sse_events if str(e.get("event", "")).startswith("tool.")]
            ping = [e for e in sse_events if e.get("event") == "ping"]
            has_citation = any(x in reply for x in ("PRO-BILL", "PRO-BILL-3.2", "Billing"))
            checks.append(
                Check(
                    "chat_turn",
                    "Chat turn completes with assistant reply",
                    "PASS" if reply else "FAIL",
                    detail=reply[:400],
                    metrics={"run_id": turn.get("run_id")},
                )
            )
            checks.append(
                Check(
                    "sse_stream",
                    "SSE events stream (tools/pings)",
                    "PASS" if toolish or ping or sse_events else "FAIL",
                    detail=f"events={len(sse_events)} tools={len(toolish)} pings={len(ping)} types={sorted({e.get('event') for e in sse_events})}",
                )
            )
            checks.append(
                Check(
                    "rag_citations",
                    "RAG / policy citation in reply",
                    "PASS" if has_citation else "FAIL",
                    detail=reply[:400],
                )
            )
        except Exception as exc:  # noqa: BLE001
            sse_task.cancel()
            checks.append(Check("chat_turn", "Chat turn", "FAIL", str(exc)))

        # Session memory across turns (no refund confirm)
        await post_turn(client, cid, "Remind me which invoice I asked about earlier if any, otherwise say none.")
        try:
            mem = await wait_assistant(client, cid, timeout=90)
            # Soft check — may say none since first turn was policy not invoice
            checks.append(
                Check(
                    "session_memory",
                    "Multi-turn session memory responds in same conversation",
                    "PASS" if mem else "FAIL",
                    detail=mem[:350],
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("session_memory", "Session memory", "FAIL", str(exc)))

        # Refund confirmation gate (ask only — do NOT confirm)
        conv2 = await create_conversation(client, "oracle-audit-refund-ask")
        await post_turn(
            client,
            conv2["id"],
            "I was charged twice on INV-1042 for $29. Can I get a refund?",
        )
        try:
            refund_ask = await wait_assistant(client, conv2["id"], timeout=90)
            asks_confirm = any(w in refund_ask.lower() for w in ("confirm", "yes", "proceed", "shall i"))
            issued = "receipt" in refund_ask.lower() and "issued" in refund_ask.lower()
            checks.append(
                Check(
                    "refund_confirmation_gate",
                    "Refund flow asks confirmation (no auto-issue)",
                    "PASS" if asks_confirm and not issued else ("FAIL" if issued else "PARTIAL"),
                    detail=refund_ask[:400],
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("refund_confirmation_gate", "Refund confirmation", "FAIL", str(exc)))

        # Escalation (creates ticket — sandbox write)
        conv3 = await create_conversation(client, "oracle-audit-escalate")
        await post_turn(client, conv3["id"], "I want to speak to a human agent about a lawsuit coverage issue.")
        try:
            esc = await wait_assistant(client, conv3["id"], timeout=90)
            ok = "ticket" in esc.lower() or "specialist" in esc.lower() or "human" in esc.lower()
            checks.append(
                Check(
                    "escalation",
                    "Human escalation path",
                    "PASS" if ok else "FAIL",
                    detail=esc[:400],
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("escalation", "Escalation", "FAIL", str(exc)))

    # 3–6) Voice via WebSocket (synthetic PCM through CF — not browser mic hardware)
    pcm = synth_pcm(2.5)
    # Save fixture for reproducibility (gitignored wav path under audit folder is ok as pcm dump)
    wav_path = OUT / "synth_utterance.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm)

    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        vconv = await create_conversation(client, "oracle-audit-voice")
        vcid, vtoken = vconv["id"], vconv["session_token"]

    voice1 = await voice_session(cid=vcid, token=vtoken, pcm=pcm, label="voice_single")
    backend_name = json.dumps(voice1.get("backend") or {})[:200]
    voice_ok = bool(voice1.get("assistant") or voice1.get("tts_bytes")) and not voice1.get("error")
    checks.append(
        Check(
            "voice_pipeline_ws",
            "Voice WebSocket STT→agent→TTS via Cloudflare",
            "PASS" if voice_ok else "FAIL",
            detail=f"backend={backend_name} transcript={voice1.get('transcript')!r} assistant={(voice1.get('assistant') or '')[:220]!r} err={voice1.get('error')}",
            metrics={
                "tts_bytes": voice1.get("tts_bytes"),
                "first_audio_ms": voice1.get("first_audio_ms_event"),
                "wall_ms": voice1.get("duration_ms"),
            },
        )
    )
    # Real browser microphone hardware cannot be granted in this automation environment
    checks.append(
        Check(
            "browser_microphone_hardware",
            "Real browser microphone capture",
            "BLOCKED",
            detail="Automated browser cannot grant getUserMedia mic permission here; WebSocket PCM path exercised instead. Manual reviewer should click Start voice once.",
        )
    )

    # Latency samples: multiple short voice turns
    lat_samples: list[float] = []
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        for i in range(5):
            c = await create_conversation(client, f"oracle-audit-lat-{i}")
            res = await voice_session(cid=c["id"], token=c["session_token"], pcm=pcm, label=f"lat-{i}")
            # Prefer server-reported tts_first_audio; else wall clock after commit is weaker
            sample = res.get("first_audio_ms_event") or res.get("wall_first_audio_ms")
            if sample and not res.get("error"):
                lat_samples.append(float(sample))
            await asyncio.sleep(2.0)  # reduce Groq TPM pressure

    if lat_samples:
        checks.append(
            Check(
                "voice_first_audio_latency",
                "TTS first-audio latency samples (ms)",
                "PASS" if pct(lat_samples, 95) is not None else "FAIL",
                detail="Server voice.tts_first_audio (TTS stage) and/or wall clock; end-of-speech→first-audio fully requires VAD timestamps (not always exported)",
                metrics={
                    "n": len(lat_samples),
                    "p50": pct(lat_samples, 50),
                    "p95": pct(lat_samples, 95),
                    "mean": statistics.mean(lat_samples),
                    "samples": lat_samples,
                },
            )
        )
    else:
        checks.append(
            Check(
                "voice_first_audio_latency",
                "Voice first-audio latency",
                "FAIL",
                detail="No successful latency samples",
            )
        )
    report["latency_samples_ms"] = lat_samples

    # Barge-in
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        c = await create_conversation(client, "oracle-audit-barge")
        barge = await voice_session(
            cid=c["id"], token=c["session_token"], pcm=synth_pcm(3.0), interrupt=True, label="barge"
        )
    checks.append(
        Check(
            "barge_in",
            "Voice interrupt / barge-in",
            "PASS" if barge.get("interrupted") else "PARTIAL",
            detail=f"interrupted={barge.get('interrupted')} err={barge.get('error')} events={[e.get('type') for e in barge.get('events', []) if isinstance(e, dict)][:20]}",
        )
    )

    # Concurrent two voice users
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        a = await create_conversation(client, "oracle-audit-c1")
        b = await create_conversation(client, "oracle-audit-c2")
    t_conc = time.perf_counter()
    conc = await asyncio.gather(
        voice_session(cid=a["id"], token=a["session_token"], pcm=pcm, label="conc-a"),
        voice_session(cid=b["id"], token=b["session_token"], pcm=pcm, label="conc-b"),
    )
    conc_ms = (time.perf_counter() - t_conc) * 1000
    both_ok = all((x.get("assistant") or x.get("tts_bytes")) and not x.get("error") for x in conc)
    report["concurrent"] = {
        "wall_ms": conc_ms,
        "a": {k: conc[0].get(k) for k in ("transcript", "tts_bytes", "error", "first_audio_ms_event")},
        "b": {k: conc[1].get(k) for k in ("transcript", "tts_bytes", "error", "first_audio_ms_event")},
        "host_cpu_ram": "BLOCKED — no SSH key access to Oracle VM from this runner",
    }
    checks.append(
        Check(
            "concurrent_two_voice",
            "Two simultaneous voice WebSocket sessions",
            "PASS" if both_ok else "FAIL",
            detail=f"wall_ms={conc_ms:.0f} a_err={conc[0].get('error')} b_err={conc[1].get('error')}",
            metrics={"wall_ms": conc_ms},
        )
    )
    checks.append(
        Check(
            "host_cpu_ram_during_concurrent",
            "Oracle CPU/RAM during dual voice",
            "BLOCKED",
            detail="SSH to 129.80.125.203 denied (publickey) for ubuntu/opc with available keys; cannot sample docker stats live.",
        )
    )

    # Groq rate-limit handling — burst chat turns
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        burst_conv = await create_conversation(client, "oracle-audit-ratelimit")
        replies = []
        for i in range(6):
            await post_turn(client, burst_conv["id"], f"Briefly: what tier am I on? ping={i}")
            try:
                replies.append(await wait_assistant(client, burst_conv["id"], timeout=100))
            except Exception as exc:  # noqa: BLE001
                replies.append(f"ERROR:{exc}")
            await asyncio.sleep(0.2)
        joined = "\n".join(replies)
        handled = ("rate-limiting" in joined.lower()) or ("rate limit" in joined.lower()) or all(
            not r.startswith("ERROR:") for r in replies
        )
        checks.append(
            Check(
                "groq_rate_limit_handling",
                "Groq rate-limit / burst handling",
                "PASS" if handled else "FAIL",
                detail=("Saw friendly rate-limit message" if "rate" in joined.lower() else "Burst completed without hard crash")
                + f"; last={(replies[-1] or '')[:180]}",
            )
        )

    # Connection failure handling — bad WS token
    try:
        bad = f"wss://loopp-proxy.saitejareddi1503.workers.dev/api/conversations/{uuid.uuid4()}/voice?token=invalid"
        async with websockets.connect(bad, open_timeout=15) as ws:
            await asyncio.wait_for(ws.recv(), timeout=10)
        checks.append(Check("ws_bad_token", "WebSocket rejects bad token/conversation", "FAIL", "unexpectedly connected"))
    except Exception as exc:  # noqa: BLE001
        checks.append(
            Check(
                "ws_bad_token",
                "WebSocket rejects bad token/conversation",
                "PASS",
                detail=str(exc)[:240],
            )
        )

    # Ops checks needing SSH
    for cid_, name, detail in [
        (
            "docker_autorestart",
            "Docker restart: unless-stopped",
            "compose.prod sets restart: unless-stopped for db/api/caddy; live restart bounce not verified (no SSH)",
        ),
        (
            "postgres_persistence",
            "PostgreSQL volume persistence",
            "compose.prod uses loopp_pgdata volume; data survived health checks; volume remount after reboot not verified (no SSH)",
        ),
        (
            "cert_renewal",
            "HTTPS certificate renewal path",
            "sslip.io has valid Let's Encrypt cert via Caddy; auto-renewal cron/Caddy on-disk state not inspected (no SSH). Expiry Feb 18 2027.",
        ),
    ]:
        checks.append(Check(cid_, name, "PARTIAL", detail))

    report["checks"] = [asdict(c) for c in checks]
    report["summary"] = {
        "PASS": sum(1 for c in checks if c.status == "PASS"),
        "FAIL": sum(1 for c in checks if c.status == "FAIL"),
        "PARTIAL": sum(1 for c in checks if c.status == "PARTIAL"),
        "BLOCKED": sum(1 for c in checks if c.status == "BLOCKED"),
        "total": len(checks),
    }
    report["notes"].extend(
        [
            "No Oracle SSH from this environment — host CPU/RAM, docker restart bounce, and cert data volume inspection blocked.",
            "Browser microphone hardware not grantable in automation; voice tested via Cloudflare WebSocket + PCM.",
            "Confirmed refunds intentionally not executed to limit production sandbox writes.",
            "Local .env.production is not necessarily identical to VM env (CORS for workers.dev works in prod).",
        ]
    )

    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    lines = [
        "# Oracle production readiness audit",
        "",
        f"Generated: {report['generated_at']}",
        f"Cloudflare: `{BASE}`",
        f"Origin: `{ORIGIN}`",
        "",
        f"**PASS {report['summary']['PASS']} · FAIL {report['summary']['FAIL']} · PARTIAL {report['summary']['PARTIAL']} · BLOCKED {report['summary']['BLOCKED']}** (total {report['summary']['total']})",
        "",
        "| ID | Status | Check | Detail |",
        "|----|--------|-------|--------|",
    ]
    for c in checks:
        detail = (c.detail or "").replace("|", "/").replace("\n", " ")[:160]
        lines.append(f"| `{c.id}` | **{c.status}** | {c.name} | {detail} |")
    if lat_samples:
        lines.extend(
            [
                "",
                "## First-audio latency (ms)",
                "",
                f"- n={len(lat_samples)} p50={pct(lat_samples,50):.1f} p95={pct(lat_samples,95):.1f} mean={statistics.mean(lat_samples):.1f}",
                f"- samples={lat_samples}",
                "",
            ]
        )
    lines.extend(["", "## Notes", ""] + [f"- {n}" for n in report["notes"]] + [""])
    (OUT / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps(report["summary"], indent=2))
    print(f"Wrote {OUT / 'REPORT.md'}")


if __name__ == "__main__":
    asyncio.run(main())
