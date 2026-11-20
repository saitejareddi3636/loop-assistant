import { useEffect, useRef, useState } from "react";
import { Waveform } from "./Waveform";

type Props = {
  conversationId: string | null;
  sessionToken: string | null;
  disabled?: boolean;
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

export function VoiceControls({
  conversationId,
  sessionToken,
  disabled,
  onUserTranscript,
  onAssistantText,
  onError,
  onMetric,
}: Props) {
  const [enabled, setEnabled] = useState(false);
  const [state, setState] = useState<VoiceState>("idle");
  const [caption, setCaption] = useState("");
  const [levels, setLevels] = useState<number[]>(() => Array.from({ length: 24 }, () => 0.08));
  const [backend, setBackend] = useState<string>("");

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

  useEffect(() => {
    return () => {
      void teardown();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    stopCapture();
    wsRef.current?.close();
    wsRef.current = null;
    await playbackCtxRef.current?.close().catch(() => undefined);
    playbackCtxRef.current = null;
    nextPlayTimeRef.current = 0;
    setState("idle");
    setEnabled(false);
  }

  function toPcm16k(input: Float32Array, inputRate: number): Int16Array {
    // Box-filter decimation: averaging each window avoids the aliasing that
    // point sampling causes, which badly hurts STT accuracy.
    const ratio = inputRate / 16000;
    const newLen = Math.floor(input.length / ratio);
    const out = new Int16Array(newLen);
    for (let i = 0; i < newLen; i++) {
      const start = Math.floor(i * ratio);
      const end = Math.max(start + 1, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = start; j < end; j++) sum += input[j] ?? 0;
      const s = Math.max(-1, Math.min(1, sum / (end - start)));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
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
    for (let i = 0; i < samples; i++) {
      channel[i] = view.getInt16(i * 2, true) / 32768;
    }
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    // TTS on the VM runs close to real time, so keep a small lead buffer
    // whenever playback has drained to avoid audible gaps.
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
    window.setTimeout(() => void teardown(), remainingMs + 100);
  }

  function stopPlayback() {
    generationRef.current += 1;
    nextPlayTimeRef.current = 0;
    void playbackCtxRef.current?.close().catch(() => undefined);
    playbackCtxRef.current = new AudioContext();
  }

  const micAvailable = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  const needsHttps = typeof window !== "undefined" && (!window.isSecureContext || !micAvailable);
  const httpsUrl =
    typeof window !== "undefined" ? `https://${window.location.host}${window.location.pathname}` : "";

  async function startVoice() {
    if (!conversationId || !sessionToken || disabled) return;
    setState("connecting");
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error(
          `Microphone requires HTTPS. Open ${httpsUrl || "https://<this-host>"} , accept the certificate warning, then Start voice.`,
        );
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
      streamRef.current = stream;
      // Ask the browser to resample the mic to 16 kHz with proper filtering.
      // Some browsers refuse to mix sample rates; fall back to the default rate.
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
      // Prefer same-origin vite proxy when available.
      const wsUrl = `${proto}://${window.location.host}/api/conversations/${conversationId}/voice?token=${encodeURIComponent(sessionToken)}`;
      const ws = new WebSocket(wsUrl);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        setEnabled(true);
        setState("listening");
      };
      ws.onerror = () => onError("Voice socket error");
      ws.onclose = () => {
        if (wsRef.current === ws) void teardown();
      };
      ws.onmessage = (event) => {
        if (typeof event.data !== "string") {
          const buf = event.data as ArrayBuffer;
          if (buf.byteLength < 8) return;
          const header = new DataView(buf, 0, 8);
          const generation = header.getUint32(0, true);
          const pcm = buf.slice(8);
          queuePlayback(pcm, generation);
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
          onAssistantText(String(msg.text ?? ""));
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
        // Waveform levels from actual samples
        let sum = 0;
        for (let i = 0; i < input.length; i += 32) sum += Math.abs(input[i] ?? 0);
        const level = Math.min(1, (sum / (input.length / 32)) * 4);
        setLevels((prev) => [...prev.slice(1), level]);
        if (ws.readyState === WebSocket.OPEN && !stopPendingRef.current) {
          const pcm = toPcm16k(input, audioCtx.sampleRate);
          // Copy into a plain ArrayBuffer for WebSocket typing / SharedArrayBuffer safety.
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
    }
  }

  async function toggle() {
    if (stopPendingRef.current) {
      await teardown();
      return;
    }
    if (enabled) {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || state === "idle") {
        await teardown();
        return;
      }
      // Stop the mic now, but let the server transcribe and answer whatever
      // was already said before the socket closes.
      stopPendingRef.current = true;
      stopCapture();
      setState("finishing");
      if (state === "listening" || state === "hearing you" || state === "interrupted") {
        ws.send(JSON.stringify({ type: "voice.commit" }));
      } else if (state !== "transcribing" && state !== "thinking" && state !== "speaking") {
        await teardown();
        return;
      }
      stopTimerRef.current = window.setTimeout(() => void teardown(), STOP_TIMEOUT_MS);
      return;
    }
    await startVoice();
  }

  function interrupt() {
    wsRef.current?.send(JSON.stringify({ type: "voice.interrupt" }));
    stopPlayback();
    setState("interrupted");
  }

  const waveTone =
    state === "speaking"
      ? "speak"
      : state === "interrupted" || state === "finishing"
        ? "alert"
        : state === "listening" || state === "hearing you"
          ? "listen"
          : "idle";

  const stateLabel =
    state === "hearing you"
      ? "Hearing you"
      : state === "finishing"
        ? "Finishing"
        : state.charAt(0).toUpperCase() + state.slice(1);

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-2">
      <div className="rounded-[1.35rem] border border-ink-200/80 bg-white/85 p-3.5 shadow-soft backdrop-blur sm:p-4">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={!conversationId || !sessionToken || disabled}
            onClick={() => void toggle()}
            className={`inline-flex min-h-11 items-center justify-center rounded-xl px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-45 ${
              enabled
                ? "bg-coral hover:brightness-110 focus-visible:outline-coral"
                : "bg-ink-900 hover:bg-ink-700 focus-visible:outline-ink-900"
            }`}
          >
            {state === "finishing" ? "End now" : enabled ? "Stop voice" : "Start voice"}
          </button>
          {enabled ? (
            <button
              type="button"
              onClick={interrupt}
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-ink-200 bg-white px-3.5 py-2.5 text-sm font-medium text-ink-900 transition hover:bg-ink-50"
            >
              Interrupt
            </button>
          ) : null}

          <div className="flex min-w-[148px] flex-1 items-center gap-3 sm:min-w-[180px]">
            <div className="min-w-0">
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${
                  enabled
                    ? "bg-accent-soft text-accent-deep"
                    : "bg-ink-50 text-ink-700/55"
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    enabled ? "animate-pulse-dot bg-accent" : "bg-ink-300"
                  }`}
                />
                {stateLabel}
              </span>
              <div className="mt-1.5">
                <Waveform levels={levels} active={enabled} tone={waveTone} />
              </div>
            </div>
          </div>

          <div className="min-w-0 flex-[1.4] basis-full text-xs text-ink-700/80 sm:basis-auto">
            <p className="truncate text-sm text-ink-900">
              {caption || (enabled ? "Listening for your question…" : "Live captions appear here")}
            </p>
            <p className="mt-0.5 truncate font-mono text-[10px] text-ink-700/45">
              {backend || "Voice backend loads on start"}
            </p>
            {needsHttps && !enabled ? (
              <p className="mt-1.5 text-[11px] text-amber-800">
                Mic needs HTTPS.{" "}
                <a className="font-semibold underline" href={httpsUrl}>
                  Open secure link
                </a>
                , then start voice.
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
