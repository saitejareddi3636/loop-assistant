import { useState } from "react";
import type { FormEvent } from "react";

type Props = {
  disabled?: boolean;
  busy?: boolean;
  onSend: (text: string) => Promise<void> | void;
};

export function Composer({ disabled, busy, onSend }: Props) {
  const [text, setText] = useState("");
  const canSend = !disabled && !busy && Boolean(text.trim());

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value || disabled || busy) return;
    setText("");
    await onSend(value);
  }

  return (
    <form
      onSubmit={(e) => void handleSubmit(e)}
      className="mx-auto flex w-full max-w-3xl items-end gap-2 px-4 pb-3 pt-1 sm:gap-3 sm:pb-4"
    >
      <label className="sr-only" htmlFor="composer">
        Message
      </label>
      <div className="relative min-w-0 flex-1">
        <textarea
          id="composer"
          rows={2}
          value={text}
          disabled={disabled || busy}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSubmit(e);
            }
          }}
          placeholder={busy ? "Waiting for the agent…" : "Describe the issue…"}
          className="min-h-[56px] w-full resize-none rounded-2xl border border-ink-200/90 bg-white/95 px-4 py-3.5 text-sm text-ink-900 shadow-soft outline-none ring-accent/25 placeholder:text-ink-700/35 focus:border-accent/40 focus:ring-2 disabled:opacity-60"
        />
        <p className="pointer-events-none absolute bottom-2 right-3 hidden text-[10px] text-ink-700/35 sm:block">
          Enter to send
        </p>
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
  );
}
