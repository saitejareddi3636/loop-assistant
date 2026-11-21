import { useEffect, useRef, useState } from "react";
import { speakText } from "../lib/api";

type Props = {
  text: string;
  conversationId: string;
  sessionToken: string;
  onError?: (message: string) => void;
};

export function SpeakButton({ text, conversationId, sessionToken, onError }: Props) {
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function stop() {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.src = "";
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setPlaying(false);
    setLoading(false);
  }

  async function toggle() {
    if (playing || loading) {
      stop();
      return;
    }
    const clipped = text.trim();
    if (!clipped) return;
    setLoading(true);
    try {
      const blob = await speakText(conversationId, sessionToken, clipped);
      const url = URL.createObjectURL(blob);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => stop();
      audio.onerror = () => {
        stop();
        onError?.("Could not play speech audio");
      };
      await audio.play();
      setLoading(false);
      setPlaying(true);
    } catch (err) {
      stop();
      onError?.(err instanceof Error ? err.message : "Speech failed");
    }
  }

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      aria-label={playing ? "Stop speaking" : loading ? "Loading speech" : "Read aloud"}
      aria-pressed={playing}
      title={playing ? "Stop" : "Read aloud"}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-lg transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
        playing
          ? "bg-accent text-white"
          : loading
            ? "bg-accent-soft text-accent-deep"
            : "text-ink-700/55 hover:bg-ink-50 hover:text-ink-900"
      }`}
    >
      {loading ? <SpinnerIcon /> : playing ? <StopIcon /> : <SpeakerIcon />}
    </button>
  );
}

function SpeakerIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M11 5 6 9H3v6h3l5 4V5Z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      <path
        d="M15.5 8.5a5 5 0 0 1 0 7M18.5 6a9 9 0 0 1 0 12"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden className="animate-spin">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
