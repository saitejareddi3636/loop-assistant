import { useCallback, useEffect, useRef, useState } from "react";
import { Composer } from "./components/Composer";
import { LiveVoiceModal } from "./components/LiveVoiceModal";
import { MessageList } from "./components/MessageList";
import { ObservabilityDrawer } from "./components/ObservabilityDrawer";
import { ToolStatus } from "./components/ToolStatus";
import {
  cancelPendingConfirmation,
  createConversation,
  createTurn,
  getConversation,
  getHealth,
  retryFailedRun,
} from "./lib/api";
import type { ChatMessage, ObsMetric, StreamEvent, ToolStatusItem } from "./lib/types";

function newTurnId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `turn_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function toolDetail(payload: Record<string, unknown>): string | undefined {
  if (typeof payload.ticket_id === "string") return `Ticket ${payload.ticket_id}`;
  if (typeof payload.invoice_id === "string") return `Invoice ${payload.invoice_id}`;
  if (typeof payload.tier === "string") return `Tier ${payload.tier}`;
  if (typeof payload.count === "number") return `${payload.count} policy hit(s)`;
  if (typeof payload.error === "string") return payload.error;
  return undefined;
}

function toolStatusFromEvent(
  eventType: string,
  payload: Record<string, unknown>,
): ToolStatusItem["status"] {
  if (payload.error === "confirmation_required") return "awaiting";
  if (eventType === "tool.started") return "started";
  if (eventType === "tool.completed") return "completed";
  return "failed";
}

type FailedOp = {
  runId: string;
  source: "chat" | "voice";
  retryAfterSeconds: number | null;
  waitRequired: boolean;
};

export default function App() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toolItems, setToolItems] = useState<ToolStatusItem[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [busy, setBusy] = useState(false);
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [failedOp, setFailedOp] = useState<FailedOp | null>(null);
  const [healthLabel, setHealthLabel] = useState("Connecting…");
  const [healthOk, setHealthOk] = useState(false);
  const [obsOpen, setObsOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(true);
  const [traces, setTraces] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<ObsMetric[]>([]);
  const [liveVoiceOpen, setLiveVoiceOpen] = useState(false);
  const lastSequence = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryInFlight = useRef(false);
  const activeRetryId = useRef<string | null>(null);

  const connectEvents = useCallback((id: string, after = 0) => {
    eventSourceRef.current?.close();
    const source = new EventSource(`/api/conversations/${id}/events?after=${after}`);
    eventSourceRef.current = source;

    const handlePayload = (raw: MessageEvent) => {
      try {
        const event = JSON.parse(raw.data) as StreamEvent;
        if (event.sequence <= lastSequence.current) return;
        lastSequence.current = event.sequence;

        if (
          event.event_type === "tool.started" ||
          event.event_type === "tool.completed" ||
          event.event_type === "tool.failed"
        ) {
          const tool = String(event.payload.tool ?? "tool");
          const status = toolStatusFromEvent(event.event_type, event.payload);
          setToolItems((prev) => {
            const withoutSame = prev.filter((item) => !(item.tool === tool && item.status === "started"));
            return [
              ...withoutSame,
              {
                id: `${event.sequence}-${tool}`,
                tool,
                status,
                detail: toolDetail(event.payload),
                at: Date.now(),
              },
            ];
          });
          setTraces((prev) => [`${event.event_type} · ${tool}`, ...prev].slice(0, 40));
        }

        if (event.event_type === "assistant.delta") {
          setStreamingText(String(event.payload.text ?? ""));
        }

        if (event.event_type === "assistant.ui") {
          setTraces((prev) => [`assistant.ui · ${JSON.stringify(event.payload)}`, ...prev].slice(0, 40));
        }

        if (event.event_type === "confirmation.cancelled") {
          setTraces((prev) => ["confirmation.cancelled", ...prev].slice(0, 40));
          void getConversation(id).then((detail) => setMessages(detail.messages));
        }

        if (event.event_type === "obs.metrics") {
          setMetrics((prev) => [...prev, event.payload as ObsMetric]);
          setTraces((prev) =>
            [
              `obs · tokens=${String(event.payload.total_tokens_est ?? "?")} cost=$${String(event.payload.estimated_cost_usd ?? "?")}`,
              ...prev,
            ].slice(0, 40),
          );
        }

        if (event.event_type === "run.completed") {
          setBusy(false);
          setStreamingText("");
          setFailedOp(null);
          setError(null);
          retryInFlight.current = false;
          activeRetryId.current = null;
          void getConversation(id).then((detail) => setMessages(detail.messages));
        }

        if (event.event_type === "run.failed") {
          setBusy(false);
          setStreamingText("");
          retryInFlight.current = false;
          const retry = Boolean(event.payload.retryable);
          const src = event.payload.source === "voice" ? "voice" : "chat";
          const wait = event.payload.retry_after_seconds;
          const waitRequired = Boolean(event.payload.wait_required);
          setError(
            String(event.payload.user_message ?? event.payload.error ?? "Agent run failed"),
          );
          if (retry && event.run_id) {
            setFailedOp({
              runId: event.run_id,
              source: src,
              retryAfterSeconds: typeof wait === "number" ? wait : null,
              waitRequired,
            });
          } else {
            setFailedOp(null);
          }
          void getConversation(id).then((detail) => setMessages(detail.messages));
        }
      } catch {
        // ignore malformed ping/payloads
      }
    };

    source.onmessage = handlePayload;
    for (const name of [
      "run.started",
      "run.completed",
      "run.failed",
      "tool.started",
      "tool.completed",
      "tool.failed",
      "assistant.delta",
      "assistant.ui",
      "confirmation.cancelled",
      "obs.metrics",
    ]) {
      source.addEventListener(name, handlePayload as EventListener);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        const health = await getHealth();
        if (!cancelled) {
          setHealthOk(true);
          setHealthLabel(health.llm_configured ? "Online" : "Online · LLM not configured");
        }
        const conversation = await createConversation();
        if (cancelled) return;
        setConversationId(conversation.id);
        setSessionToken(conversation.session_token ?? null);
        connectEvents(conversation.id, 0);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to start session");
          setHealthLabel("Offline");
          setHealthOk(false);
        }
      } finally {
        if (!cancelled) setBooting(false);
      }
    }

    void boot();
    return () => {
      cancelled = true;
      eventSourceRef.current?.close();
    };
  }, [connectEvents]);

  const onSend = useCallback(
    async (text: string) => {
      if (!conversationId || busy) return;
      setError(null);
      setFailedOp(null);
      setBusy(true);
      setToolItems([]);
      setStreamingText("");

      const turnId = newTurnId();
      setMessages((prev) => [
        ...prev,
        {
          id: `local-${turnId}`,
          role: "user",
          content: text,
          client_turn_id: turnId,
          created_at: new Date().toISOString(),
        },
      ]);

      try {
        await createTurn(conversationId, text, turnId);
      } catch (err) {
        setBusy(false);
        setError(err instanceof Error ? err.message : "Failed to send message");
      }
    },
    [busy, conversationId],
  );

  const onRetryFailed = useCallback(async () => {
    if (!conversationId || !failedOp || busy || retryInFlight.current) return;
    retryInFlight.current = true;
    setBusy(true);
    setError(null);
    setToolItems([]);
    setStreamingText("");
    if (!activeRetryId.current) {
      activeRetryId.current = newTurnId();
    }
    const clientRetryId = activeRetryId.current;
    try {
      const result = await retryFailedRun(conversationId, failedOp.runId, clientRetryId);
      if (result.reused) {
        setTraces((prev) => [`retry reused · ${result.run_id}`, ...prev].slice(0, 40));
      }
    } catch (err) {
      setBusy(false);
      retryInFlight.current = false;
      setError(err instanceof Error ? err.message : "Retry failed");
    }
  }, [busy, conversationId, failedOp]);

  const onCancelConfirmation = useCallback(async () => {
    if (!conversationId) return;
    try {
      await cancelPendingConfirmation(conversationId);
      setMessages((prev) =>
        prev.map((m) => {
          const ui = m.meta?.ui;
          if (!ui || typeof ui !== "object" || !("confirmation" in (ui as object))) return m;
          const nextUi = { ...(ui as Record<string, unknown>) };
          delete nextUi.confirmation;
          return { ...m, meta: { ...m.meta, ui: nextUi } };
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel confirmation");
    }
  }, [conversationId]);

  const retryLabel = failedOp?.source === "voice" ? "Retry voice turn" : "Retry last turn";

  return (
    <div className="relative flex min-h-screen min-h-dvh flex-col bg-sage">
      <a
        href="#composer"
        className="absolute left-4 top-4 z-50 -translate-y-16 rounded-lg bg-white px-3 py-2 text-sm text-ink-900 opacity-0 shadow-soft transition focus:translate-y-0 focus:opacity-100 focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-accent"
      >
        Skip to message
      </a>

      <header className="sticky top-0 z-20 border-b border-ink-200/50 bg-sage/90 backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-3.5 sm:px-6">
          <div className="min-w-0">
            <p className="font-display text-2xl tracking-tight text-ink-900 sm:text-[1.7rem]">
              Loopp
            </p>
            <p className="mt-0.5 text-xs text-muted">Customer care</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-xl border border-ink-200 bg-white px-3 py-1.5 text-xs font-medium text-ink-700 transition hover:bg-ink-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent lg:hidden"
              onClick={() => setActivityOpen((v) => !v)}
              aria-expanded={activityOpen}
              aria-controls="activity-sidebar"
            >
              {activityOpen ? "Hide activity" : "Activity"}
            </button>
            {!healthOk && !booting ? (
              <p className="text-xs font-medium text-coral" title={healthLabel}>
                Can’t reach support right now
              </p>
            ) : null}
          </div>
        </div>
      </header>

      <div className="relative z-10 mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col lg:flex-row">
        <main id="main" className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          {booting ? (
            <div className="flex flex-1 flex-col justify-center px-4 py-10 sm:px-6">
              <div className="rounded-2xl bg-white p-8 shadow-soft">
                <div className="skeleton-bar h-3 w-40" />
                <div className="skeleton-bar mt-4 h-3 w-full" />
                <div className="skeleton-bar mt-2 h-3 w-4/5" />
                <p className="mt-6 text-sm text-muted">Starting your support session…</p>
              </div>
            </div>
          ) : (
            <MessageList
              messages={messages}
              streamingText={streamingText || undefined}
              busy={busy}
              conversationId={conversationId}
              sessionToken={sessionToken}
              onSuggestion={conversationId && !busy ? (text) => void onSend(text) : undefined}
              onCancelConfirmation={conversationId ? () => void onCancelConfirmation() : undefined}
              onError={setError}
            />
          )}

          <div className="dock sticky bottom-0 z-20 pt-2">
            {error ? (
              <div
                className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-4 pb-2 sm:px-6"
                role="alert"
                aria-live="assertive"
              >
                <div className="flex items-start justify-between gap-3 rounded-xl border border-coral/20 bg-coral-soft px-3 py-2">
                  <p className="text-sm text-coral">{error}</p>
                  <button
                    type="button"
                    onClick={() => {
                      setError(null);
                      setFailedOp(null);
                      activeRetryId.current = null;
                    }}
                    className="shrink-0 rounded-lg px-2 py-1 text-xs font-medium text-muted transition hover:bg-white/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    Dismiss
                  </button>
                </div>
                {failedOp ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      disabled={busy || retryInFlight.current}
                      onClick={() => void onRetryFailed()}
                      className="rounded-xl bg-accent px-3.5 py-2 text-sm font-medium text-white transition hover:bg-accent-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
                    >
                      {retryLabel}
                    </button>
                    {failedOp.retryAfterSeconds != null ? (
                      <p className="text-xs text-muted">
                        {failedOp.waitRequired
                          ? `Wait about ${Math.ceil(failedOp.retryAfterSeconds)}s, then retry.`
                          : `Provider suggested waiting ~${Math.ceil(failedOp.retryAfterSeconds)}s if this keeps failing.`}
                      </p>
                    ) : (
                      <p className="text-xs text-muted">
                        Retries the same {failedOp.source} turn — no duplicate user message.
                      </p>
                    )}
                  </div>
                ) : null}
              </div>
            ) : null}
            <Composer
              conversationId={conversationId}
              sessionToken={sessionToken}
              disabled={!conversationId || booting}
              busy={busy}
              onSend={onSend}
              onError={setError}
              onOpenLiveVoice={() => setLiveVoiceOpen(true)}
              liveVoiceDisabled={busy || booting || liveVoiceOpen}
            />
          </div>
        </main>

        <aside
          id="activity-sidebar"
          className={`${
            activityOpen ? "flex" : "hidden"
          } w-full flex-col border-t border-ink-200/40 bg-white/80 lg:flex lg:w-[280px] lg:shrink-0 lg:border-l lg:border-t-0`}
        >
          <div className="flex items-center justify-between px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Activity</p>
            <span className="rounded-full bg-sage px-2 py-0.5 text-[10px] font-medium text-muted">
              {toolItems.length}
            </span>
          </div>
          <div className="flex-1 overflow-y-auto px-3 pb-3">
            <ToolStatus items={toolItems} compact />
          </div>
          <div className="border-t border-ink-100 px-2 py-1">
            <ObservabilityDrawer
              compact
              open={obsOpen}
              onToggle={() => setObsOpen((v) => !v)}
              traces={traces}
              metrics={metrics}
            />
          </div>
        </aside>
      </div>

      <LiveVoiceModal
        open={liveVoiceOpen}
        conversationId={conversationId}
        sessionToken={sessionToken}
        onClose={() => setLiveVoiceOpen(false)}
        onUserTranscript={(text) => {
          if (!text) return;
          setFailedOp(null);
          setError(null);
          setMessages((prev) => [
            ...prev,
            {
              id: `voice-user-${Date.now()}`,
              role: "user",
              content: text,
              created_at: new Date().toISOString(),
            },
          ]);
        }}
        onAssistantText={(text) => {
          if (!text) return;
          setMessages((prev) => [
            ...prev,
            {
              id: `voice-asst-${Date.now()}`,
              role: "assistant",
              content: text,
              created_at: new Date().toISOString(),
            },
          ]);
        }}
        onError={setError}
        onMetric={(metric) => setMetrics((prev) => [...prev, metric as ObsMetric])}
      />
    </div>
  );
}
