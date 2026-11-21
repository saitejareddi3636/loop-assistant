from __future__ import annotations

import time
import uuid
import wave
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import run_agent_turn
from app.config import get_settings
from app.db.models import AgentRun, Conversation, Message
from app.events.bus import EventBus
from app.voice.factory import get_voice_stack
from harness.assertions import check_expectation
from harness.env import EVALS_ROOT
from harness.schema import Scenario, ScenarioResult, TurnResult
from harness.traces import conversation_snapshot, load_tool_events

AUDIO_DIR = EVALS_ROOT / "fixtures" / "audio"


def _read_wav_pcm16(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        if wf.getsampwidth() != 2 or wf.getnchannels() != 1:
            raise ValueError(f"Expected mono PCM16 wav: {path}")
        return frames, rate


def _synthesize_fixture_wav(text: str, path: Path, *, rate: int = 16000) -> None:
    """Generate a deterministic tone-modulated placeholder if macOS `say` unavailable.

    Prefer `say` on Darwin for realistic STT; fall back to speech-like noise bursts
    so the suite still exercises the pipeline wiring.
    """
    import platform
    import shutil
    import subprocess
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin" and shutil.which("say"):
        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
            aiff = tmp.name
        subprocess.run(["say", "-o", aiff, text], check=True)
        # Convert via afconvert or python
        if shutil.which("afconvert"):
            subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, str(path)],
                check=True,
            )
            Path(aiff).unlink(missing_ok=True)
            return
        Path(aiff).unlink(missing_ok=True)

    # Fallback: amplitude-modulated noise (not for WER claims — labeled synthetic).
    duration = max(1.5, min(8.0, 0.08 * len(text)))
    n = int(rate * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    carrier = 0.15 * np.sin(2 * np.pi * 180 * t)
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
    audio = (carrier * env * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(audio.tobytes())


def ensure_audio_fixture(fixture_id: str, text: str) -> Path:
    path = AUDIO_DIR / f"{fixture_id}.wav"
    if not path.exists():
        _synthesize_fixture_wav(text, path)
    return path


async def run_voice_live_scenario(session: AsyncSession, scenario: Scenario) -> ScenarioResult:
    """Real STT → LangGraph → TTS using production adapters (no WebSocket)."""
    settings = get_settings()
    stack = get_voice_stack()
    bus = EventBus()
    conversation = Conversation(customer_id=scenario.customer_id, title=f"eval-voice:{scenario.id}")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    turn_results: list[TurnResult] = []
    t_suite = time.perf_counter()
    artifacts: dict[str, Any] = {"tts_files": []}

    try:
        for idx, turn in enumerate(scenario.turns):
            timings: dict[str, float] = {}
            transcript = turn.inject_transcript
            pcm: bytes | None = None
            rate = settings.voice_input_sample_rate

            if transcript is None:
                fixture_id = turn.audio_fixture or f"{scenario.id}_t{idx}"
                wav_path = ensure_audio_fixture(fixture_id, turn.user)
                pcm, rate = _read_wav_pcm16(wav_path)
                t0 = time.perf_counter()
                stt_out = await stack.stt.transcribe(pcm, rate)
                timings["stt"] = (time.perf_counter() - t0) * 1000
                transcript = (stt_out.text or "").strip()
            user_text = transcript or turn.user

            run_id = uuid.uuid4()
            client_turn_id = f"voice-eval-{uuid.uuid4()}"
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
                    content=user_text,
                    client_turn_id=client_turn_id,
                    run_id=run_id,
                    meta={"source": "voice", "eval_scenario": scenario.id, "stt_raw": transcript},
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
                user_text=user_text,
                source="voice",
                extra_metrics={"eval_scenario": scenario.id, **timings},
            )
            timings["agent_turn"] = (time.perf_counter() - t0) * 1000

            # Real TTS — capture bytes + first-audio latency
            tts_buf = bytearray()
            t0 = time.perf_counter()
            first_ms = None
            async for chunk in stack.tts.synthesize_stream(reply):
                if first_ms is None:
                    first_ms = (time.perf_counter() - t0) * 1000
                    timings["tts_first_audio"] = first_ms
                tts_buf.extend(chunk)
            timings["tts_total"] = (time.perf_counter() - t0) * 1000
            timings["e2e_voice"] = (time.perf_counter() - t_suite) * 1000

            out_wav = EVALS_ROOT / "failures" / "_runs" / scenario.id / f"tts_t{idx}.wav"
            out_wav.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(out_wav), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(stack.tts.sample_rate)
                # TTS may already be PCM16
                wf.writeframes(bytes(tts_buf))
            artifacts["tts_files"].append(str(out_wav))

            events = [e for e in await load_tool_events(session, conversation.id) if e.get("run_id") == str(run_id)]
            assertions = await check_expectation(
                session,
                turn.expect,
                response=reply,
                events=events,
                conversation_id=conversation.id,
                transcript=transcript,
                tts_bytes=len(tts_buf),
                timings_ms=timings,
            )
            turn_results.append(
                TurnResult(
                    user_text=turn.user,
                    transcript=transcript,
                    assistant_text=reply,
                    tool_events=events,
                    assertions=assertions,
                    timings_ms=timings,
                    tts_bytes=len(tts_buf),
                )
            )

        failed = [tr for tr in turn_results if not tr.passed]
        status = "PASS" if not failed else "FAIL"
        explanation = "; ".join(
            f"{a.name}: {a.detail}" for tr in failed for a in tr.assertions if not a.passed
        )
        snap = await conversation_snapshot(session, conversation.id)
        return ScenarioResult(
            scenario_id=scenario.id,
            name=scenario.name,
            kind=scenario.kind,
            status=status,
            expected_behavior=scenario.expected_behavior or scenario.description,
            actual_behavior=(turn_results[-1].assistant_text if turn_results else "")[:500],
            failure_explanation=explanation,
            turns=turn_results,
            tool_trace=await load_tool_events(session, conversation.id),
            timings_ms={"scenario_total": (time.perf_counter() - t_suite) * 1000},
            artifacts_dir=str(EVALS_ROOT / "failures" / "_runs" / scenario.id),
            used_real={
                "stt": stack.stt.name,
                "llm": True,
                "tools": True,
                "rag": True,
                "tts": stack.tts.name,
            },
            debug={"snapshot": snap, "artifacts": artifacts, "backend": stack.backend},
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
            used_real={"stt": True, "llm": True, "tools": True, "rag": True, "tts": True},
            debug={"error": repr(exc)},
        )


async def run_voice_sim_scenario(session: AsyncSession, scenario: Scenario) -> ScenarioResult:
    """Deterministic barge-in / interrupt simulation without loading STT/TTS weights."""
    from app.voice.session import VoiceSession, VoiceSessionState

    class _DummyWS:
        def __init__(self) -> None:
            self.messages: list[Any] = []

        async def send_text(self, data: str) -> None:
            self.messages.append(("text", data))

        async def send_bytes(self, data: bytes) -> None:
            self.messages.append(("bytes", len(data)))

        async def close(self, code: int = 1000) -> None:
            self.messages.append(("close", code))

    conversation = Conversation(customer_id=scenario.customer_id, title=f"eval-sim:{scenario.id}")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    ws = _DummyWS()
    voice = VoiceSession(ws, conversation.id)  # type: ignore[arg-type]
    voice.state = VoiceSessionState(conversation_id=conversation.id, customer_id=scenario.customer_id)
    voice.state.speaking = True
    voice.state.listening = False
    gen_before = voice.state.generation

    t0 = time.perf_counter()
    await voice._on_control({"type": "voice.interrupt"})
    stop_ms = (time.perf_counter() - t0) * 1000
    stopped = voice.state.generation > gen_before and voice.state.listening and not voice.state.speaking

    expect = scenario.turns[0].expect if scenario.turns else scenario.expect
    assertions = await check_expectation(
        session,
        expect,
        response="interrupted",
        events=[],
        conversation_id=conversation.id,
        timings_ms={"barge_in_stopped": 1.0 if stopped else 0.0, "interrupt_stop_ms": stop_ms},
    )
    # Also assert stop latency budget if provided
    turn = TurnResult(
        user_text="(barge-in)",
        transcript=None,
        assistant_text="interrupted",
        tool_events=[],
        assertions=assertions,
        timings_ms={"interrupt_stop_ms": stop_ms, "barge_in_stopped": 1.0 if stopped else 0.0},
    )
    status = "PASS" if turn.passed and stopped else "FAIL"
    return ScenarioResult(
        scenario_id=scenario.id,
        name=scenario.name,
        kind=scenario.kind,
        status=status,
        expected_behavior=scenario.expected_behavior or scenario.description,
        actual_behavior=f"stopped={stopped} stop_ms={stop_ms:.1f}",
        failure_explanation="" if status == "PASS" else "barge-in did not stop speech cleanly",
        turns=[turn],
        timings_ms={"interrupt_stop_ms": stop_ms},
        used_real={"stt": False, "llm": False, "tools": False, "rag": False, "tts": False},
        debug={"ws_messages": ws.messages[:20]},
    )
