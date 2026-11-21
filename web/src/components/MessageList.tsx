import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import {
  assistantUiFromMeta,
  extractAmountHint,
  extractInvoiceHint,
} from "../lib/messageUi";
import type { ChatMessage } from "../lib/types";
import { MarkdownText } from "./MarkdownText";
import { SpeakButton } from "./SpeakButton";

type Props = {
  messages: ChatMessage[];
  streamingText?: string;
  busy?: boolean;
  conversationId?: string | null;
  sessionToken?: string | null;
  onSuggestion?: (text: string) => void;
  onCancelConfirmation?: () => void;
  onError?: (message: string) => void;
};

const SUGGESTIONS = [
  "I was charged twice on INV-1042. Can you help?",
  "What is my account tier?",
  "What is the Pro refund policy?",
];

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function MessageList({
  messages,
  streamingText,
  busy,
  conversationId,
  sessionToken,
  onSuggestion,
  onCancelConfirmation,
  onError,
}: Props) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "end",
    });
  }, [messages, streamingText, busy]);

  const empty = messages.length === 0 && !streamingText;

  return (
    <div className="scroll-fade mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 overflow-y-auto px-4 py-6 sm:px-6 sm:py-8">
      {empty ? (
        <div className="animate-fade-up mx-auto w-full max-w-xl py-10 sm:py-16">
          <h1 className="font-display text-3xl tracking-tight text-ink-900 sm:text-[2.35rem]">
            How can we help?
          </h1>
          <p className="mt-3 max-w-md text-[15px] leading-relaxed text-muted">
            Ask about billing, invoices, or refunds. I can look up your account and policies in real
            time.
          </p>
          <div className="mt-8 flex flex-col gap-2.5">
            {SUGGESTIONS.map((text) => (
              <button
                key={text}
                type="button"
                disabled={!onSuggestion}
                onClick={() => onSuggestion?.(text)}
                className="rounded-2xl border border-ink-200/70 bg-white px-4 py-3.5 text-left text-sm text-ink-900 shadow-soft transition hover:border-accent/35 hover:bg-bubble/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
              >
                {text}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {messages.map((message, index) => {
        const isLatestConfirm =
          !message.meta?.superseded &&
          Boolean(assistantUiFromMeta(message.meta).confirmation) &&
          !messages.slice(index + 1).some(
            (m) =>
              !m.meta?.superseded && Boolean(assistantUiFromMeta(m.meta).confirmation),
          );
        return (
          <MessageBubble
            key={message.id}
            message={message}
            showConfirmationCard={isLatestConfirm}
            onCancelConfirmation={isLatestConfirm ? onCancelConfirmation : undefined}
            conversationId={conversationId}
            sessionToken={sessionToken}
            onError={onError}
            style={{ animationDelay: `${Math.min(index, 6) * 40}ms` }}
          />
        );
      })}

      {busy && !streamingText ? (
        <div className="animate-fade-up flex justify-start">
          <div className="rounded-2xl bg-white px-4 py-3.5 shadow-soft">
            <div className="flex items-center gap-2.5 text-sm text-muted">
              <span className="flex gap-1" aria-hidden>
                <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent" />
                <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent [animation-delay:300ms]" />
              </span>
              Thinking…
            </div>
          </div>
        </div>
      ) : null}

      {streamingText ? (
        <div className="animate-fade-up flex justify-start">
          <div className="max-w-[min(100%,36rem)] rounded-2xl rounded-bl-md bg-white px-4 py-3.5 text-[15px] leading-relaxed text-ink-900 shadow-soft">
            <div className="streaming-cursor">
              <MarkdownText text={streamingText} />
            </div>
          </div>
        </div>
      ) : null}

      <div ref={endRef} />
    </div>
  );
}

function MessageBubble({
  message,
  style,
  showConfirmationCard = false,
  onCancelConfirmation,
  conversationId,
  sessionToken,
  onError,
}: {
  message: ChatMessage;
  style?: CSSProperties;
  showConfirmationCard?: boolean;
  onCancelConfirmation?: () => void;
  conversationId?: string | null;
  sessionToken?: string | null;
  onError?: (message: string) => void;
}) {
  const isUser = message.role === "user";
  const superseded = Boolean(message.meta?.superseded);
  const ui = !isUser && !superseded ? assistantUiFromMeta(message.meta) : {};
  const invoice = extractInvoiceHint(ui);
  const amount = extractAmountHint(ui);
  const showConfirm = showConfirmationCard && Boolean(ui.confirmation);
  const showEscalation = Boolean(ui.escalation);
  const canSpeak = !isUser && Boolean(conversationId && sessionToken && message.content.trim());

  return (
    <div
      className={`animate-fade-up flex ${isUser ? "justify-end" : "justify-start"}`}
      style={style}
    >
      <div className={`max-w-[min(100%,36rem)] space-y-2 ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`rounded-2xl px-4 py-3.5 text-[15px] leading-relaxed ${
            isUser
              ? "rounded-br-md bg-bubble text-ink-900"
              : "rounded-bl-md bg-white text-ink-900 shadow-soft"
          }`}
        >
          <div className="mb-1.5 flex items-center justify-between gap-3">
            <p className="text-[11px] font-medium text-muted">
              {isUser ? "You" : "Loopp"}
            </p>
            <div className="flex items-center gap-1.5">
              {canSpeak && conversationId && sessionToken ? (
                <SpeakButton
                  text={message.content}
                  conversationId={conversationId}
                  sessionToken={sessionToken}
                  onError={onError}
                />
              ) : null}
              <time
                className="text-[10px] tabular-nums text-muted/70"
                dateTime={message.created_at}
              >
                {formatTime(message.created_at)}
              </time>
            </div>
          </div>
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : (
            <MarkdownText text={message.content} />
          )}
        </div>

        {showConfirm ? (
          <div className="rounded-2xl border border-accent/20 bg-bubble/70 p-3.5 shadow-soft">
            <p className="text-xs font-semibold text-accent">Confirmation needed</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {invoice ? (
                <span className="rounded-full bg-white/80 px-2.5 py-1 text-xs font-medium text-ink-900">
                  {invoice}
                </span>
              ) : null}
              {amount ? (
                <span className="rounded-full bg-white/80 px-2.5 py-1 text-xs font-medium text-ink-900">
                  {amount}
                </span>
              ) : null}
            </div>
            <p className="mt-2 text-xs leading-relaxed text-ink-700/80">
              Reply “yes, confirm the refund” when you’re ready. Nothing is charged until you confirm.
            </p>
            {onCancelConfirmation ? (
              <button
                type="button"
                onClick={onCancelConfirmation}
                className="mt-2 rounded-lg px-2 py-1 text-xs font-medium text-ink-700/80 transition hover:bg-white/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                Cancel confirmation
              </button>
            ) : null}
          </div>
        ) : null}

        {showEscalation ? (
          <div className="rounded-2xl border border-coral/20 bg-coral-soft/70 p-3.5 shadow-soft">
            <p className="text-xs font-semibold text-coral">Escalation</p>
            <p className="mt-1.5 text-xs leading-relaxed text-ink-700/85">
              Human-review ticket {ui.escalation?.ticket_id} is open.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}
