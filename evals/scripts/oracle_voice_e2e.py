#!/usr/bin/env python3
"""Spoken customer request through Cloudflare WebSocket voice path.

Generates speech audio (macOS `say` when available), streams PCM over the
public Worker WebSocket, and records transcript / tools / TTS / EOS latency.
Does not deploy or mutate Oracle config.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import websockets

BASE = "https://loopp-proxy.saitejareddi1503.workers.dev"
OUT = Path(__file__).resolve().parents[1] / "results" / "oracle_audit"
OUT.mkdir(parents=True, exist_ok=True)
UTTERANCE = "I was charged twice on invoice INV-1042 for twenty nine dollars. Can you help with a refund?"


def make_wav(text: str, path: Path, rate: int = 16000) -> None:
    if shutil.which("say") and shutil.which("afconvert"):
        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
            aiff = tmp.name
        subprocess.run(["say", "-r", "180", "-o", aiff, text], check=True)
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{rate}", "-c", "1", aiff, str(path)],
            check=True,
        )
        Path(aiff).unlink(missing_ok=True)
        return
    # Fallback tone burst (labeled synthetic)
    duration = max(2.5, min(8.0, 0.07 * len(text)))
    n = int(rate * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    audio = (0.2 * np.sin(2 * np.pi * 210 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 2.5 * t)))
    pcm = (audio * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


async def main() -> None:
    # Diagnostics first (why Whisper vs Moonshine)
    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as client:
        try:
            diag_resp = await client.get("/api/voice/diagnostics")
            diag = diag_resp.json() if diag_resp.status_code == 200 else {
                "http_status": diag_resp.status_code,
                "body": diag_resp.text[:500],
                "note": "diagnostics endpoint not deployed on production yet",
            }
        except Exception as exc:  # noqa: BLE001
            diag = {"error": str(exc), "note": "diagnostics endpoint may not be deployed yet"}
        conv = (await client.post("/api/conversations", json={"title": "spoken-e2e"})).json()
        cid, token = conv["id"], conv["session_token"]

    wav = OUT / "spoken_inv1042.wav"
    make_wav(UTTERANCE, wav)
    with wave.open(str(wav), "rb") as wf:
        rate = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())

    ws_url = f"wss://loopp-proxy.saitejareddi1503.workers.dev/api/conversations/{cid}/voice?token={token}"
    events: list[dict] = []
    tts_bytes = 0
    result: dict = {"utterance": UTTERANCE, "diagnostics": diag}
    client_eos_t0: float | None = None
    client_first_audio_t: float | None = None

    async with websockets.connect(ws_url, max_size=8 * 1024 * 1024, open_timeout=60) as ws:
        # Wait for backend
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=90)
            if isinstance(msg, bytes):
                continue
            payload = json.loads(msg)
            events.append(payload)
            if payload.get("type") == "voice.backend":
                result["backend"] = payload
                break
            if payload.get("type") == "voice.error":
                result["error"] = payload
                break

        frame = int(rate * 0.02) * 2
        for i in range(0, len(pcm), frame):
            await ws.send(pcm[i : i + frame])
            await asyncio.sleep(0.02)
        # Trailing silence to trip VAD end-of-speech
        silence = b"\x00" * frame * 45
        for i in range(0, len(silence), frame):
            await ws.send(silence[i : i + frame])
            await asyncio.sleep(0.02)
        # Client EOS clock: last audio + commit → first TTS byte (includes network + STT + agent + TTS).
        client_eos_t0 = time.perf_counter()
        await ws.send(json.dumps({"type": "voice.commit"}))

        deadline = time.perf_counter() + 150
        while time.perf_counter() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                break
            if isinstance(msg, bytes):
                if client_first_audio_t is None and client_eos_t0 is not None:
                    client_first_audio_t = time.perf_counter()
                tts_bytes += max(0, len(msg) - 8)
                continue
            payload = json.loads(msg)
            events.append(payload)
            if payload.get("type") == "voice.speak_done":
                break

    # Pull tool trace via REST conversation + we only have WS events for voice metrics
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        detail = (await client.get(f"/api/conversations/{cid}")).json()
        # SSE replay for tools
        tool_events = []
        async with client.stream(
            "GET",
            f"/api/conversations/{cid}/events?after=0",
            headers={"Accept": "text/event-stream"},
        ) as resp:
            n = 0
            async for line in resp.aiter_lines():
                if line.startswith("event:") and "tool." in line:
                    tool_events.append(line)
                n += 1
                if n > 80:
                    break

    first = next((e for e in events if e.get("type") == "voice.tts_first_audio"), None)
    transcript = next((e for e in events if e.get("type") == "voice.transcript"), None)
    assistant = next((e for e in events if e.get("type") == "voice.assistant_text"), None)

    client_eos_ms = None
    if client_eos_t0 is not None and client_first_audio_t is not None:
        client_eos_ms = (client_first_audio_t - client_eos_t0) * 1000

    server_eos = (first or {}).get("eos_to_first_audio_ms")
    # Prefer server metric when deployed; always record client wall-clock EOS.
    result.update(
        {
            "transcript": (transcript or {}).get("text"),
            "stt_provider": (transcript or {}).get("stt_provider"),
            "assistant": (assistant or {}).get("text"),
            "tts_bytes": tts_bytes,
            "tts_first_audio": first,
            "eos_to_first_audio_ms": server_eos if server_eos is not None else client_eos_ms,
            "server_eos_to_first_audio_ms": server_eos,
            "client_eos_to_first_audio_ms": client_eos_ms,
            "stt_latency_ms": (first or {}).get("stt_latency_ms") or (transcript or {}).get("stt_ms"),
            "agent_latency_ms": (first or {}).get("agent_latency_ms") or (assistant or {}).get("agent_ms"),
            "messages": detail.get("messages"),
            "tool_event_lines": tool_events[:40],
            "ws_event_types": [e.get("type") for e in events if isinstance(e, dict)],
        }
    )

    # Pass criteria for this probe
    text = (result.get("transcript") or "").lower()
    assistant_text = (result.get("assistant") or "").lower()
    checks = {
        "got_transcript": bool(text),
        "transcript_mentions_invoice_or_1042": ("1042" in text) or ("invoice" in text),
        "got_assistant": bool(assistant_text),
        "got_tts_audio": tts_bytes > 1000,
        "has_eos_metric": result.get("eos_to_first_audio_ms") is not None,
        "got_tool_events": len(tool_events) > 0,
    }
    result["checks"] = checks
    result["passed"] = all(
        [
            checks["got_transcript"],
            checks["got_assistant"],
            checks["got_tts_audio"],
            checks["has_eos_metric"],
        ]
    )

    out = OUT / "spoken_e2e.json"
    out.write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "checks": checks,
                "backend": result.get("backend"),
                "eos_to_first_audio_ms": result.get("eos_to_first_audio_ms"),
                "client_eos_to_first_audio_ms": result.get("client_eos_to_first_audio_ms"),
                "server_eos_to_first_audio_ms": result.get("server_eos_to_first_audio_ms"),
                "stt_provider": result.get("stt_provider"),
                "transcript": result.get("transcript"),
                "assistant": (result.get("assistant") or "")[:160],
                "out": str(out),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
