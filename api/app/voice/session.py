from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from fastapi import WebSocket

from app.agent.runner import run_agent_turn
from app.config import get_settings
from app.db.models import AgentRun, Conversation, Message
from app.db.session import async_session_factory
from app.events.bus import event_bus
from app.observability.metrics import estimate_chat_cost
from app.voice.factory import get_voice_stack
from app.voice.speech_normalize import normalize_transcript_ids

# Whisper-family models emit these on near-silent clips.
_SILENCE_HALLUCINATIONS = {"you", "thank you", "thanks for watching", "bye"}

@dataclass
class VoiceSessionState:
    conversation_id: uuid.UUID
    customer_id: str
    sample_rate: int = 16000
    generation: int = 0
    listening: bool = True
    speaking: bool = False
    pcm_buffer: bytearray = field(default_factory=bytearray)
    frame_remainder: bytearray = field(default_factory=bytearray)
    speech_frames: int = 0
    silence_frames: int = 0
    barge_frames: int = 0
    in_speech: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)


class VoiceSession:
    """Bidirectional voice session sharing the chat conversation + LangGraph runner."""

    def __init__(self, websocket: WebSocket, conversation_id: uuid.UUID) -> None:
        self.ws = websocket
        self.conversation_id = conversation_id
        self.state: VoiceSessionState | None = None
        self._speak_task: asyncio.Task | None = None
        self._stack = None

    async def run(self) -> None:
        settings = get_settings()
        async with async_session_factory() as session:
            conversation = await session.get(Conversation, self.conversation_id)
            if conversation is None:
                await self.ws.close(code=4404)
                return
            self.state = VoiceSessionState(
                conversation_id=conversation.id,
                customer_id=conversation.customer_id,
                sample_rate=settings.voice_input_sample_rate,
            )

        await self.ws.accept()
        await self._send_json(
            {
                "type": "voice.ready",
                "conversation_id": str(self.conversation_id),
                "input_sample_rate": self.state.sample_rate,
                "vad": "pending",
            }
        )

        # Lazy-load models after accept so the socket is live.
        self._stack = await asyncio.to_thread(get_voice_stack)
        await self._send_json(
            {
                "type": "voice.backend",
                "backend": self._stack.backend,
                "tts_sample_rate": self._stack.tts.sample_rate,
            }
        )

        try:
            while True:
                message = await self.ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if "bytes" in message and message["bytes"] is not None:
                    await self._on_audio(message["bytes"])
                elif "text" in message and message["text"] is not None:
                    await self._on_control(json.loads(message["text"]))
        finally:
            await self._cancel_speech()

    async def _send_json(self, payload: dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(payload))

    async def _on_control(self, payload: dict[str, Any]) -> None:
        assert self.state is not None
        kind = payload.get("type")
        if kind == "voice.interrupt":
            t0 = time.perf_counter()
            await self._cancel_speech()
            self.state.generation += 1
            self.state.listening = True
            stop_ms = (time.perf_counter() - t0) * 1000
            self.state.metrics["interrupt_stop_ms"] = stop_ms
            await self._send_json({"type": "voice.interrupted", "stop_ms": stop_ms, "generation": self.state.generation})
        elif kind == "voice.commit":
            await self._finalize_utterance()
        elif kind == "voice.cancel":
            self.state.pcm_buffer.clear()
            self.state.frame_remainder.clear()
            self.state.in_speech = False
            self.state.speech_frames = 0
            self.state.silence_frames = 0

    # Frame counts below are in VAD frames (512 samples @ 16 kHz = 32 ms).
    _SPEECH_START_FRAMES = 3
    _SILENCE_END_FRAMES = 22  # ~700 ms of silence ends the utterance
    _PREROLL_FRAMES = 10  # keep ~320 ms before speech onset
    _BARGE_IN_FRAMES = 10  # ~320 ms of confident speech while the agent talks
    _BARGE_IN_PROB = 0.85

    async def _on_audio(self, pcm16: bytes) -> None:
        assert self.state is not None and self._stack is not None
        frame_bytes = self._stack.vad.frame_samples * 2
        self.state.frame_remainder.extend(pcm16)
        while len(self.state.frame_remainder) >= frame_bytes:
            frame = bytes(self.state.frame_remainder[:frame_bytes])
            del self.state.frame_remainder[:frame_bytes]
            await self._on_frame(frame)

    async def _on_frame(self, frame: bytes) -> None:
        assert self.state is not None and self._stack is not None
        prob = self._speech_probability(frame)

        if not self.state.listening:
            # Agent is thinking or speaking. Only a sustained, confident voice
            # counts as barge-in so speaker echo does not cut playback.
            if self.state.speaking and prob >= self._BARGE_IN_PROB:
                self.state.barge_frames += 1
                if self.state.barge_frames >= self._BARGE_IN_FRAMES:
                    self.state.barge_frames = 0
                    await self._on_control({"type": "voice.interrupt"})
            else:
                self.state.barge_frames = 0
            return

        is_speech = prob >= get_settings().voice_vad_threshold
        self.state.pcm_buffer.extend(frame)

        if not self.state.in_speech:
            if is_speech:
                self.state.speech_frames += 1
                if self.state.speech_frames >= self._SPEECH_START_FRAMES:
                    self.state.in_speech = True
                    self.state.silence_frames = 0
                    await self._send_json({"type": "voice.speech_started"})
            else:
                self.state.speech_frames = 0
            if not self.state.in_speech:
                keep = self._PREROLL_FRAMES * len(frame)
                if len(self.state.pcm_buffer) > keep:
                    del self.state.pcm_buffer[:-keep]
            return

        if is_speech:
            self.state.silence_frames = 0
        else:
            self.state.silence_frames += 1

        max_bytes = int(get_settings().voice_max_utterance_seconds * self.state.sample_rate * 2)
        if self.state.silence_frames >= self._SILENCE_END_FRAMES or len(self.state.pcm_buffer) >= max_bytes:
            await self._finalize_utterance()

    def _speech_probability(self, frame: bytes) -> float:
        assert self._stack is not None
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        return self._stack.vad.speech_probability(audio.tobytes())

    async def _finalize_utterance(self) -> None:
        assert self.state is not None and self._stack is not None
        pcm = bytes(self.state.pcm_buffer)
        self.state.pcm_buffer.clear()
        self.state.in_speech = False
        self.state.speech_frames = 0
        self.state.silence_frames = 0
        if len(pcm) < self.state.sample_rate * 0.25 * 2:
            await self._send_json({"type": "voice.ignored", "reason": "too_short"})
            return

        # End-of-speech clock: silence VAD just committed this utterance.
        eos_t0 = time.perf_counter()
        self.state.metrics["eos_t0"] = eos_t0

        await self._send_json({"type": "voice.transcribing", "eos_ms": 0})
        t0 = time.perf_counter()
        try:
            transcript = await self._stack.stt.transcribe(pcm, self.state.sample_rate)
        except Exception as exc:  # noqa: BLE001
            await self._send_json({"type": "voice.error", "error": f"stt_failed: {exc}"})
            return
        stt_ms = (time.perf_counter() - t0) * 1000
        self.state.metrics["stt_latency_ms"] = stt_ms
        text = normalize_transcript_ids(transcript.text.strip())
        await self._send_json(
            {
                "type": "voice.transcript",
                "text": text,
                "is_final": True,
                "stt_ms": stt_ms,
                "stt_provider": self._stack.stt.name,
            }
        )
        if not text or text.lower().strip(" .!?") in _SILENCE_HALLUCINATIONS:
            await self._send_json({"type": "voice.ignored", "reason": "no_speech"})
            return

        # Hand off into the same LangGraph turn pipeline as chat.
        self.state.listening = False
        try:
            reply = await self._run_agent(text)
        except Exception as exc:  # noqa: BLE001
            reply = ""
            await self._send_json({"type": "voice.error", "error": f"agent_failed: {exc}"})
        if reply:
            await self._speak(reply, eos_t0=eos_t0)
        else:
            self.state.listening = True
            await self._send_json({"type": "voice.speak_done", "generation": self.state.generation})

    async def _run_agent(self, user_text: str) -> str:
        assert self.state is not None
        run_id = uuid.uuid4()
        client_turn_id = f"voice-{uuid.uuid4()}"
        async with async_session_factory() as session:
            conversation = await session.get(Conversation, self.conversation_id)
            if conversation is None:
                await self._send_json({"type": "voice.error", "error": "conversation_missing"})
                return ""
            session.add(
                AgentRun(
                    id=run_id,
                    conversation_id=self.conversation_id,
                    client_turn_id=client_turn_id,
                    status="running",
                )
            )
            session.add(
                Message(
                    conversation_id=self.conversation_id,
                    role="user",
                    content=user_text,
                    client_turn_id=client_turn_id,
                    run_id=run_id,
                    meta={"source": "voice"},
                )
            )
            await session.commit()

            t0 = time.perf_counter()
            reply = await run_agent_turn(
                session,
                event_bus,
                conversation_id=self.conversation_id,
                run_id=run_id,
                customer_id=self.state.customer_id,
                user_text=user_text,
                source="voice",
                extra_metrics={
                    **self.state.metrics,
                    "voice_backend": self._stack.backend if self._stack else None,
                },
            )
            agent_ms = (time.perf_counter() - t0) * 1000
            self.state.metrics["agent_latency_ms"] = agent_ms
            cost = estimate_chat_cost(
                model=get_settings().llm_model,
                prompt_chars=len(user_text),
                completion_chars=len(reply),
            )

        await self._send_json(
            {
                "type": "voice.assistant_text",
                "text": reply,
                "run_id": str(run_id),
                "agent_ms": self.state.metrics.get("agent_latency_ms"),
                "cost": cost,
            }
        )
        return reply

    async def _speak(self, text: str, *, eos_t0: float | None = None) -> None:
        assert self.state is not None and self._stack is not None
        generation = self.state.generation
        self.state.speaking = True
        await self._send_json(
            {
                "type": "voice.speaking",
                "generation": generation,
                "sample_rate": self._stack.tts.sample_rate,
                "tts_provider": self._stack.tts.name,
            }
        )

        async def _stream() -> None:
            assert self.state is not None and self._stack is not None
            t0 = time.perf_counter()
            first_ms = None
            seq = 0
            try:
                async for chunk in self._stack.tts.synthesize_stream(text):
                    if self.state.generation != generation:
                        break
                    if first_ms is None:
                        first_ms = (time.perf_counter() - t0) * 1000
                        self.state.metrics["tts_first_audio_ms"] = first_ms
                        eos_to_first = None
                        if eos_t0 is not None:
                            eos_to_first = (time.perf_counter() - eos_t0) * 1000
                            self.state.metrics["eos_to_first_audio_ms"] = eos_to_first
                        await self._send_json(
                            {
                                "type": "voice.tts_first_audio",
                                "ms": first_ms,
                                "tts_first_audio_ms": first_ms,
                                "eos_to_first_audio_ms": eos_to_first,
                                "stt_latency_ms": self.state.metrics.get("stt_latency_ms"),
                                "agent_latency_ms": self.state.metrics.get("agent_latency_ms"),
                            }
                        )
                    # Prefix 8-byte header: generation(uint32) + sequence(uint32)
                    header = generation.to_bytes(4, "little") + seq.to_bytes(4, "little")
                    await self.ws.send_bytes(header + chunk)
                    seq += 1
                self.state.metrics["tts_total_ms"] = (time.perf_counter() - t0) * 1000
            except Exception as exc:  # noqa: BLE001
                await self._send_json({"type": "voice.error", "error": f"tts_failed: {exc}"})
            finally:
                self.state.speaking = False
                self.state.listening = True
                await self._send_json(
                    {
                        "type": "voice.speak_done",
                        "generation": generation,
                        "tts_total_ms": self.state.metrics.get("tts_total_ms"),
                        "eos_to_first_audio_ms": self.state.metrics.get("eos_to_first_audio_ms"),
                    }
                )

        self._speak_task = asyncio.create_task(_stream())

    async def _cancel_speech(self) -> None:
        assert self.state is not None
        self.state.generation += 1
        self.state.speaking = False
        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()
            try:
                await self._speak_task
            except asyncio.CancelledError:
                pass
        self._speak_task = None
