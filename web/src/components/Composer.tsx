import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { encodeWav, formatTimer, toPcm16k } from "../lib/audio";
import { transcribeAudio } from "../lib/api";
import { Waveform } from "./Waveform";

type Props = {
  conversationId: string | null;
  sessionToken: string | null;
  disabled?: boolean;
  busy?: boolean;
  onSend: (text: string) => Promise<void> | void;
  onError?: (message: string) => void;
  onOpenLiveVoice?: () => void;
  liveVoiceDisabled?: boolean;
};

type DictationPhase = "idle" | "recording" | "transcribing";

const MAX_RECORD_MS = 60_000;
const LEVEL_BARS = 32;

export function Composer({
  conversationId,
  sessionToken,
  disabled,
  busy,
  onSend,
  onError,
  onOpenLiveVoice,
  liveVoiceDisabled,
}: Props) {
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<DictationPhase>("idle");
  const [levels, setLevels] = useState<number[]>(() => Array.from({ length: LEVEL_BARS }, () => 0.08));
  const [elapsedMs, setElapsedMs] = useState(0);
  const [dictationHint, setDictationHint] = useState<string | null>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Int16Array[]>([]);
  const sampleRateRef = useRef(16000);
  const startedAtRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const phaseRef = useRef<DictationPhase>("idle");

  phaseRef.current = phase;
  const canSend = !disabled && !busy && phase === "idle" && Boolean(text.trim());
  const micBusy = phase !== "idle";

  useEffect(() => {
    return () => {
      stopCapture();
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
    };
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
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }

  async function startDictation() {
    if (!conversationId || !sessionToken || disabled || busy || micBusy) return;
    setDictationHint(null);
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("Microphone requires HTTPS (secure context).");
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
      sourceRef.current = source;
      sampleRateRef.current = 16000;
      chunksRef.current = [];
      startedAtRef.current = performance.now();
      setElapsedMs(0);
      setLevels(Array.from({ length: LEVEL_BARS }, () => 0.08));
      setPhase("recording");

      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      processor.onaudioprocess = (e) => {
        if (phaseRef.current !== "recording") return;
        const input = e.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < input.length; i += 32) sum += Math.abs(input[i] ?? 0);
        const level = Math.min(1, (sum / (input.length / 32)) * 4);
        setLevels((prev) => [...prev.slice(1), level]);
        const pcm = toPcm16k(input, audioCtx.sampleRate);
        chunksRef.current.push(pcm);
        if (performance.now() - startedAtRef.current >= MAX_RECORD_MS) {
          void finishDictation();
        }
      };
      source.connect(processor);
      processor.connect(audioCtx.destination);

      timerRef.current = window.setInterval(() => {
        setElapsedMs(performance.now() - startedAtRef.current);
      }, 200);
    } catch (err) {
      stopCapture();
      setPhase("idle");
      onError?.(err instanceof Error ? err.message : "Microphone permission denied");
    }
  }

  function cancelDictation() {
    stopCapture();
    chunksRef.current = [];
    setPhase("idle");
    setElapsedMs(0);
    setDictationHint(null);
  }

  async function finishDictation() {
    if (phaseRef.current !== "recording") return;
    setPhase("transcribing");
    stopCapture();

    const parts = chunksRef.current;
    chunksRef.current = [];
    let total = 0;
    for (const p of parts) total += p.length;
    if (total < 1600) {
      setPhase("idle");
      setDictationHint("Recording too short — try again.");
      return;
    }
    const merged = new Int16Array(total);
    let offset = 0;
    for (const p of parts) {
      merged.set(p, offset);
      offset += p.length;
    }
    const wav = encodeWav(merged, sampleRateRef.current);

    if (!conversationId || !sessionToken) {
      setPhase("idle");
      onError?.("Session not ready for transcription");
      return;
    }

    try {
      const result = await transcribeAudio(conversationId, sessionToken, wav, sampleRateRef.current);
      const transcript = (result.text || "").trim();
      if (!transcript) {
        setDictationHint("No speech detected — nothing was sent.");
      } else {
        setText((prev) => (prev.trim() ? `${prev.trim()} ${transcript}` : transcript));
        setDictationHint("Review the transcript, then press Send.");
      }
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Transcription failed");
    } finally {
      setPhase("idle");
      setElapsedMs(0);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value || disabled || busy || phase !== "idle") return;
    setText("");
    setDictationHint(null);
    await onSend(value);
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-3 pt-1 sm:pb-4">
      {phase === "recording" || phase === "transcribing" ? (
        <div
          className="mb-2 overflow-hidden rounded-2xl border border-ink-200/80 bg-white/95 p-3 shadow-soft sm:p-4"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span
                className={`h-2.5 w-2.5 rounded-full ${
                  phase === "recording" ? "animate-pulse-dot bg-coral" : "bg-accent"
                }`}
              />
              <p className="text-sm font-semibold text-ink-900">
                {phase === "recording" ? "Recording" : "Transcribing…"}
              </p>
              <span className="font-mono text-xs text-ink-700/55">{formatTimer(elapsedMs)}</span>
            </div>
            <p className="hidden text-[11px] text-ink-700/45 sm:block">Silence never sends</p>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <Waveform
              levels={levels}
              active={phase === "recording"}
              tone={phase === "recording" ? "listen" : "idle"}
            />
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={cancelDictation}
                disabled={phase === "transcribing"}
                className="rounded-xl border border-ink-200 bg-white px-3.5 py-2 text-sm font-medium text-ink-900 transition hover:bg-ink-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void finishDictation()}
                disabled={phase !== "recording"}
                className="rounded-xl bg-ink-900 px-3.5 py-2 text-sm font-semibold text-white transition hover:bg-ink-700 disabled:opacity-50"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <form onSubmit={(e) => void handleSubmit(e)} className="flex items-end gap-2 sm:gap-3">
        <label className="sr-only" htmlFor="composer">
          Message
        </label>
        <div className="relative min-w-0 flex-1">
          <textarea
            id="composer"
            name="message"
            rows={2}
            value={text}
            autoComplete="off"
            disabled={disabled || busy || micBusy}
            onChange={(e) => {
              setText(e.target.value);
              if (dictationHint) setDictationHint(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSubmit(e);
              }
            }}
            placeholder={
              busy
                ? "Waiting for the agent…"
                : micBusy
                  ? "Finish or cancel recording…"
                  : "Describe the issue… or use the mic to dictate"
            }
            className="min-h-[56px] w-full resize-none rounded-2xl border border-ink-200/90 bg-white/95 py-3.5 pl-4 pr-24 text-sm text-ink-900 shadow-soft outline-none ring-accent/25 placeholder:text-ink-700/35 focus:border-accent/40 focus:ring-2 focus-visible:ring-2 disabled:opacity-60"
          />
          <div className="absolute bottom-2 right-2 flex items-center gap-1">
            <button
              type="button"
              aria-label="Dictate with microphone"
              title="Dictate"
              disabled={!conversationId || !sessionToken || disabled || busy || micBusy}
              onClick={() => void startDictation()}
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl text-ink-700 transition hover:bg-ink-50 hover:text-ink-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              <MicIcon />
            </button>
            {onOpenLiveVoice ? (
              <button
                type="button"
                aria-label="Open live voice conversation"
                title="Live voice"
                disabled={liveVoiceDisabled || !conversationId || !sessionToken || disabled || busy || micBusy}
                onClick={onOpenLiveVoice}
                className="inline-flex h-9 items-center justify-center gap-1 rounded-xl px-2 text-xs font-semibold text-ink-700 transition hover:bg-accent-soft hover:text-accent-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40"
              >
                <LiveOrbIcon />
                Live
              </button>
            ) : null}
          </div>
        </div>
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send message"
          className="inline-flex h-[56px] shrink-0 items-center justify-center rounded-2xl bg-accent px-5 text-sm font-semibold text-white shadow-soft transition hover:bg-accent-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-ink-200 disabled:text-ink-500"
        >
          {busy ? "…" : "Send"}
        </button>
      </form>
      {dictationHint ? (
        <p className="mt-1.5 px-1 text-[11px] text-ink-700/55">{dictationHint}</p>
      ) : (
        <p className="mt-1.5 px-1 text-[11px] text-ink-700/35">
          Mic dictates into the box — Send submits. Live opens hands-free conversation.
        </p>
      )}
    </div>
  );
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 14a3 3 0 0 0 3-3V7a3 3 0 1 0-6 0v4a3 3 0 0 0 3 3Z"
        stroke="currentColor"
        strokeWidth="1.75"
      />
      <path
        d="M19 11a7 7 0 0 1-14 0M12 18v3"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  );
}

function LiveOrbIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="7" stroke="currentColor" strokeWidth="1.75" />
      <circle cx="12" cy="12" r="3" fill="currentColor" opacity="0.55" />
    </svg>
  );
}
