import { useEffect, useId, useRef, useState } from "react";
import { toPcm16k } from "../lib/audio";
import { Waveform } from "./Waveform";

type Props = {
  open: boolean;
  conversationId: string | null;
  sessionToken: string | null;
  onClose: () => void;
  onUserTranscript: (text: string) => void;
  onAssistantText: (text: string) => void;
  onError: (message: string) => void;
  onMetric?: (metric: Record<string, unknown>) => void;
};

type VoiceState =
  | "idle"
  | "connecting"
  | "listening"
  | "hearing you"
  | "transcribing"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "finishing";

const PLAYBACK_LEAD_SECONDS = 0.3;
const STOP_TIMEOUT_MS = 30000;

/**
 * Immersive Live Conversation — Silero VAD + Moonshine STT + Pocket TTS + barge-in.
 * Closing returns to the same chat session; does not clear memory.
 */
export function LiveVoiceModal({
  open,
  conversationId,
  sessionToken,
  onClose,
  onUserTranscript,
  onAssistantText,
  onError,
  onMetric,
}: Props) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeBtnRef = useRef<HTMLButtonElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  const [state, setState] = useState<VoiceState>("idle");
  const [caption, setCaption] = useState("");
  const [levels, setLevels] = useState<number[]>(() => Array.from({ length: 28 }, () => 0.08));
  const [backend, setBackend] = useState("");
  const [orbLevel, setOrbLevel] = useState(0.2);

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const playbackCtxRef = useRef<AudioContext | null>(null);
  const nextPlayTimeRef = useRef(0);
  const generationRef = useRef(0);
  const ttsSampleRateRef = useRef(24000);
  const stopPendingRef = useRef(false);
  const stopTimerRef = useRef<number | null>(null);
  const startedRef = useRef(false);
  const stateRef = useRef<VoiceState>("idle");
  stateRef.current = state;

  useEffect(() => {
    if (!open) {
      void teardown();
      return;
    }
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    if (!startedRef.current) {
      startedRef.current = true;
      void startVoice();
    }
    const focusTimer = window.setTimeout(() => closeBtnRef.current?.focus(), 50);
    return () => window.clearTimeout(focusTimer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    return () => {
      void teardown();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!open) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        void requestClose();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function stopCapture() {
    processorRef.current?.disconnect();
    sourceRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    processorRef.current = null;
    sourceRef.current = null;
    streamRef.current = null;
    void audioCtxRef.current?.close().catch(() => undefined);
    audioCtxRef.current = null;
  }

  async function teardown() {
    if (stopTimerRef.current !== null) window.clearTimeout(stopTimerRef.current);
    stopTimerRef.current = null;
    stopPendingRef.current = false;
    startedRef.current = false;
    stopCapture();
    wsRef.current?.close();
    wsRef.current = null;
    await playbackCtxRef.current?.close().catch(() => undefined);
    playbackCtxRef.current = null;
    nextPlayTimeRef.current = 0;
    setState("idle");
    setCaption("");
    setOrbLevel(0.2);
    previouslyFocused.current?.focus?.();
    previouslyFocused.current = null;
  }

  function queuePlayback(pcm16: ArrayBuffer, generation: number) {
    if (generation !== generationRef.current) return;
    const ctx = playbackCtxRef.current;
    if (!ctx) return;
    const view = new DataView(pcm16);
    const samples = pcm16.byteLength / 2;
    if (samples === 0) return;
    const buffer = ctx.createBuffer(1, samples, ttsSampleRateRef.current);
    const channel = buffer.getChannelData(0);
    let peak = 0;
    for (let i = 0; i < samples; i++) {
      const v = view.getInt16(i * 2, true) / 32768;
      channel[i] = v;
      peak = Math.max(peak, Math.abs(v));
    }
    setOrbLevel((prev) => Math.min(1, Math.max(0.25, prev * 0.6 + peak * 1.4)));
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    const startAt =
      nextPlayTimeRef.current < ctx.currentTime
        ? ctx.currentTime + PLAYBACK_LEAD_SECONDS
        : nextPlayTimeRef.current;
    src.start(startAt);
    nextPlayTimeRef.current = startAt + buffer.duration;
  }

  function finishStopIfPending() {
    if (!stopPendingRef.current) return;
    const ctx = playbackCtxRef.current;
    const remainingMs = ctx ? Math.max(0, (nextPlayTimeRef.current - ctx.currentTime) * 1000) : 0;
    window.setTimeout(() => {
      void teardown().then(onClose);
    }, remainingMs + 100);
  }

  function stopPlayback() {
    generationRef.current += 1;
    nextPlayTimeRef.current = 0;
    void playbackCtxRef.current?.close().catch(() => undefined);
    playbackCtxRef.current = new AudioContext();
  }

  async function startVoice() {
    if (!conversationId || !sessionToken) return;
    setState("connecting");
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("Live voice requires HTTPS for microphone access.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
      streamRef.current = stream;
      let audioCtx: AudioContext;
      let source: MediaStreamAudioSourceNode;
      try {
        audioCtx = new AudioContext({ sampleRate: 16000 });
        source = audioCtx.createMediaStreamSource(stream);
      } catch {
        audioCtx = new AudioContext();
        source = audioCtx.createMediaStreamSource(stream);
      }
      audioCtxRef.current = audioCtx;
      playbackCtxRef.current = new AudioContext();
      nextPlayTimeRef.current = 0;
      sourceRef.current = source;
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const wsUrl = `${proto}://${window.location.host}/api/conversations/${conversationId}/voice?token=${encodeURIComponent(sessionToken)}`;
      const ws = new WebSocket(wsUrl);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => setState("listening");
      ws.onerror = () => onError("Voice socket error");
      ws.onclose = () => {
        if (wsRef.current === ws) {
          void teardown().then(onClose);
        }
      };
      ws.onmessage = (event) => {
        if (typeof event.data !== "string") {
          const buf = event.data as ArrayBuffer;
          if (buf.byteLength < 8) return;
          const header = new DataView(buf, 0, 8);
          const generation = header.getUint32(0, true);
          queuePlayback(buf.slice(8), generation);
          return;
        }
        const msg = JSON.parse(event.data) as Record<string, unknown>;
        const type = String(msg.type ?? "");
        if (type === "voice.backend") {
          setBackend(String(msg.backend ?? ""));
          if (typeof msg.tts_sample_rate === "number") ttsSampleRateRef.current = msg.tts_sample_rate;
        }
        if (type === "voice.speech_started" && !stopPendingRef.current) setState("hearing you");
        if (type === "voice.transcript") {
          const text = String(msg.text ?? "");
          setCaption(text);
          if (text) {
            onUserTranscript(text);
            setState("thinking");
          }
          onMetric?.({ stt_latency_ms: msg.stt_ms, source: "voice" });
        }
        if (type === "voice.ignored") {
          if (stopPendingRef.current) finishStopIfPending();
          else setState("listening");
        }
        if (type === "voice.transcribing") setState("transcribing");
        if (type === "voice.speaking") {
          setState("speaking");
          generationRef.current = Number(msg.generation ?? generationRef.current);
          nextPlayTimeRef.current = 0;
        }
        if (type === "voice.assistant_text") {
          const text = String(msg.text ?? "");
          setCaption(text);
          onAssistantText(text);
          onMetric?.((msg.cost as Record<string, unknown>) ?? {});
        }
        if (type === "voice.tts_first_audio") onMetric?.({ tts_first_audio_ms: msg.ms, source: "voice" });
        if (type === "voice.interrupted") {
          setState("interrupted");
          stopPlayback();
          onMetric?.({ interrupt_stop_ms: msg.stop_ms, source: "voice" });
        }
        if (type === "voice.speak_done") {
          if (stopPendingRef.current) finishStopIfPending();
          else setState("listening");
        }
        if (type === "voice.error") {
          onError(String(msg.error ?? "Voice error"));
          finishStopIfPending();
        }
      };

      processor.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < input.length; i += 32) sum += Math.abs(input[i] ?? 0);
        const level = Math.min(1, (sum / (input.length / 32)) * 4);
        setLevels((prev) => [...prev.slice(1), level]);
        if (stateRef.current !== "speaking") {
          setOrbLevel((prev) => Math.min(1, prev * 0.55 + level * 0.9));
        }
        if (ws.readyState === WebSocket.OPEN && !stopPendingRef.current) {
          const pcm = toPcm16k(input, audioCtx.sampleRate);
          const copy = new Uint8Array(pcm.byteLength);
          copy.set(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength));
          ws.send(copy.buffer);
        }
      };
      source.connect(processor);
      processor.connect(audioCtx.destination);
    } catch (err) {
      setState("idle");
      onError(err instanceof Error ? err.message : "Microphone permission denied");
      onClose();
    }
  }

  async function requestClose() {
    const ws = wsRef.current;
    const current = stateRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || current === "idle" || current === "connecting") {
      await teardown();
      onClose();
      return;
    }
    if (stopPendingRef.current) {
      await teardown();
      onClose();
      return;
    }
    stopPendingRef.current = true;
    stopCapture();
    setState("finishing");
    if (current === "listening" || current === "hearing you" || current === "interrupted") {
      ws.send(JSON.stringify({ type: "voice.commit" }));
    } else if (current !== "transcribing" && current !== "thinking" && current !== "speaking") {
      await teardown();
      onClose();
      return;
    }
    stopTimerRef.current = window.setTimeout(() => {
      void teardown().then(onClose);
    }, STOP_TIMEOUT_MS);
  }

  function interrupt() {
    wsRef.current?.send(JSON.stringify({ type: "voice.interrupt" }));
    stopPlayback();
    setState("interrupted");
  }

  if (!open) return null;

  const stateLabel =
    state === "hearing you"
      ? "Listening"
      : state === "finishing"
        ? "Wrapping up"
        : state.charAt(0).toUpperCase() + state.slice(1);

  const waveTone =
    state === "speaking"
      ? "speak"
      : state === "interrupted" || state === "finishing"
        ? "alert"
        : state === "listening" || state === "hearing you"
          ? "listen"
          : "idle";

  const orbScale = 1 + orbLevel * 0.35;
  const captionText =
    caption ||
    (state === "connecting"
      ? "Connecting…"
      : state === "thinking"
        ? "Thinking…"
        : state === "speaking"
          ? "Speaking…"
          : "Say something when you’re ready");

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex flex-col overflow-y-auto overscroll-contain bg-[#0b1412]/95 text-white backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <div className="pointer-events-none absolute inset-0 opacity-40" aria-hidden>
        <div
          className="absolute left-1/2 top-[38%] h-[42vmin] w-[42vmin] -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{
            background:
              "radial-gradient(circle, rgba(62,168,140,0.55) 0%, rgba(62,168,140,0.12) 45%, transparent 70%)",
            transform: `translate(-50%, -50%) scale(${orbScale})`,
            transition: "transform 120ms ease-out",
          }}
        />
      </div>

      <header className="relative z-10 flex items-center justify-between px-5 py-4 sm:px-8">
        <div>
          <p id={titleId} className="text-xs font-semibold tracking-wide text-white/45">
            Live voice conversation
          </p>
          <p className="mt-1 text-sm text-white/70">Same session · Pocket TTS · barge-in</p>
        </div>
        <button
          ref={closeBtnRef}
          type="button"
          onClick={() => void requestClose()}
          className="rounded-full border border-white/15 bg-white/10 px-4 py-2 text-sm font-medium text-white transition hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
        >
          {state === "finishing" ? "End now" : "Close"}
        </button>
      </header>

      <div className="relative z-10 flex flex-1 flex-col items-center justify-center px-6 pb-8">
        <div
          className="relative flex h-[min(42vmin,220px)] w-[min(42vmin,220px)] items-center justify-center"
          aria-hidden
        >
          <div
            className={`absolute inset-0 rounded-full border border-white/10 ${
              state === "speaking" || state === "hearing you" ? "animate-pulse" : ""
            }`}
            style={{
              transform: `scale(${orbScale})`,
              background:
                state === "speaking"
                  ? "radial-gradient(circle at 40% 35%, #7fd4bc, #2f8f76 55%, #1a4d42)"
                  : "radial-gradient(circle at 40% 35%, #cfe8df, #3ea88c 55%, #1e3f36)",
              boxShadow: "0 0 60px rgba(62,168,140,0.35)",
              transition: "transform 100ms ease-out, background 200ms ease",
            }}
          />
        </div>

        <p className="mt-8 text-xs font-semibold tracking-wide text-white/50" aria-live="polite">
          {stateLabel}
        </p>
        <p
          className="mt-3 max-w-md text-center text-lg font-medium leading-snug text-white/90 sm:text-xl"
          aria-live="polite"
          aria-atomic="true"
        >
          {captionText}
        </p>
        <div className="mt-6">
          <Waveform levels={levels} active={state !== "idle"} tone={waveTone} />
        </div>
        <p className="mt-4 font-mono text-[10px] text-white/35">{backend || "Starting voice backend…"}</p>
      </div>

      <footer className="relative z-10 flex items-center justify-center gap-3 px-5 pb-8 pt-2 pb-[max(2rem,env(safe-area-inset-bottom))]">
        <button
          type="button"
          onClick={interrupt}
          disabled={state !== "speaking"}
          className="min-h-12 rounded-2xl border border-white/20 bg-white/10 px-5 text-sm font-semibold text-white transition hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:cursor-not-allowed disabled:opacity-35"
        >
          Interrupt
        </button>
        <button
          type="button"
          onClick={() => void requestClose()}
          className="min-h-12 rounded-2xl bg-coral px-6 text-sm font-semibold text-white transition hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
        >
          End live
        </button>
      </footer>
    </div>
  );
}
