import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { encodeWav, toPcm16k } from "../lib/audio";
import { transcribeAudio } from "../lib/api";

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
  const [hint, setHint] = useState<string | null>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Int16Array[]>([]);
  const sampleRateRef = useRef(16000);
  const startedAtRef = useRef(0);
  const maxTimerRef = useRef<number | null>(null);
  const phaseRef = useRef<DictationPhase>("idle");

  phaseRef.current = phase;
  const canSend = !disabled && !busy && phase === "idle" && Boolean(text.trim());
  const recording = phase === "recording";
  const transcribing = phase === "transcribing";

  useEffect(() => {
    return () => {
      stopCapture();
      if (maxTimerRef.current !== null) window.clearTimeout(maxTimerRef.current);
    };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && phaseRef.current === "recording") {
        e.preventDefault();
        cancelDictation();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
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
    if (maxTimerRef.current !== null) {
      window.clearTimeout(maxTimerRef.current);
      maxTimerRef.current = null;
    }
  }

  function cancelDictation() {
    stopCapture();
    chunksRef.current = [];
    setPhase("idle");
    setHint("Recording cancelled");
  }

  async function startDictation() {
    if (!conversationId || !sessionToken || disabled || busy || phase !== "idle") return;
    setHint(null);
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
      setPhase("recording");

      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      processor.onaudioprocess = (e) => {
        if (phaseRef.current !== "recording") return;
        const input = e.inputBuffer.getChannelData(0);
        const pcm = toPcm16k(input, audioCtx.sampleRate);
        chunksRef.current.push(pcm);
      };
      source.connect(processor);
      // Don't connect processor → destination (avoids mic feedback / monitoring).
      const silent = audioCtx.createGain();
      silent.gain.value = 0;
      processor.connect(silent);
      silent.connect(audioCtx.destination);

      maxTimerRef.current = window.setTimeout(() => {
        void finishAndSend();
      }, MAX_RECORD_MS);
    } catch (err) {
      stopCapture();
      setPhase("idle");
      onError?.(err instanceof Error ? err.message : "Microphone permission denied");
    }
  }

  async function finishAndSend() {
    if (phaseRef.current !== "recording") return;
    setPhase("transcribing");
    stopCapture();

    const parts = chunksRef.current;
    chunksRef.current = [];
    let total = 0;
    for (const p of parts) total += p.length;
    if (total < 1600) {
      setPhase("idle");
      setHint("Too short — hold the mic a moment longer.");
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
        setPhase("idle");
        setHint("No speech detected — try again.");
        return;
      }
      setText("");
      setHint(null);
      setPhase("idle");
      await onSend(transcript);
    } catch (err) {
      setPhase("idle");
      onError?.(err instanceof Error ? err.message : "Transcription failed");
    }
  }

  function toggleMic() {
    if (recording) {
      void finishAndSend();
      return;
    }
    if (transcribing || disabled || busy) return;
    void startDictation();
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value || disabled || busy || phase !== "idle") return;
    setText("");
    setHint(null);
    await onSend(value);
  }

  const micLabel = recording
    ? "Stop recording and send"
    : transcribing
      ? "Transcribing"
      : "Dictate with microphone";

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-3 pt-1 sm:pb-4">
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
            disabled={disabled || busy || phase !== "idle"}
            onChange={(e) => {
              setText(e.target.value);
              if (hint) setHint(null);
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
                : recording
                  ? "Listening… tap the mic again to send"
                  : transcribing
                    ? "Transcribing…"
                    : "Describe the issue…"
            }
            className="min-h-[56px] w-full resize-none rounded-2xl border border-ink-200/90 bg-white/95 py-3.5 pl-4 pr-24 text-sm text-ink-900 shadow-soft outline-none ring-accent/25 placeholder:text-ink-700/35 focus:border-accent/40 focus:ring-2 focus-visible:ring-2 disabled:opacity-60"
          />
          <div className="absolute bottom-2 right-2 flex items-center gap-1">
            <button
              type="button"
              aria-label={micLabel}
              aria-pressed={recording}
              title={micLabel}
              disabled={!conversationId || !sessionToken || disabled || busy || transcribing}
              onClick={toggleMic}
              className={`inline-flex h-9 w-9 items-center justify-center rounded-xl transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40 ${
                recording
                  ? "bg-coral text-white shadow-glow ring-2 ring-coral/40"
                  : transcribing
                    ? "bg-accent-soft text-accent-deep"
                    : "text-ink-700 hover:bg-ink-50 hover:text-ink-900"
              }`}
            >
              {transcribing ? <SpinnerIcon /> : <MicIcon />}
            </button>
            {onOpenLiveVoice ? (
              <button
                type="button"
                aria-label="Open live voice conversation"
                title="Live voice"
                disabled={liveVoiceDisabled || !conversationId || !sessionToken || disabled || busy || phase !== "idle"}
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
      <p className="mt-1.5 px-1 text-[11px] text-ink-700/45" aria-live="polite">
        {hint ??
          (recording
            ? "Recording — tap the mic again to transcribe and send. Esc cancels."
            : "Tap mic to talk, tap again to send. Speaker on replies reads them aloud. Live is hands-free.")}
      </p>
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

function SpinnerIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden className="animate-spin">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
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
