import { useCallback, useEffect, useRef, useState } from "react";
import { Composer } from "./components/Composer";
import { MessageList } from "./components/MessageList";
import { ObservabilityDrawer } from "./components/ObservabilityDrawer";
import { ToolStatus } from "./components/ToolStatus";
import { VoiceControls } from "./components/VoiceControls";
import { createConversation, createTurn, getConversation, getHealth } from "./lib/api";
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

export default function App() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toolItems, setToolItems] = useState<ToolStatusItem[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [busy, setBusy] = useState(false);
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [healthLabel, setHealthLabel] = useState("Connecting…");
  const [healthOk, setHealthOk] = useState(false);
  const [obsOpen, setObsOpen] = useState(false);
  const [traces, setTraces] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<ObsMetric[]>([]);
  const lastSequence = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);

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
          const status =
            event.event_type === "tool.started"
              ? "started"
              : event.event_type === "tool.completed"
                ? "completed"
                : "failed";
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
          const text = String(event.payload.text ?? "");
          setStreamingText(text);
        }

        if (event.event_type === "assistant.ui") {
          setTraces((prev) => [`assistant.ui · ${JSON.stringify(event.payload)}`, ...prev].slice(0, 40));
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
          void getConversation(id).then((detail) => {
            setMessages(detail.messages);
          });
        }

        if (event.event_type === "run.failed") {
          setBusy(false);
          setStreamingText("");
          setError(String(event.payload.error ?? "Agent run failed"));
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
          setHealthLabel(
            health.llm_configured
              ? `Online · ${health.model.replace(/^groq:/, "")}`
              : "Online · set GROQ_API_KEY",
          );
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
      setBusy(true);
      setToolItems([]);
      setStreamingText("");

      const turnId = newTurnId();
      const optimistic: ChatMessage = {
        id: `local-${turnId}`,
        role: "user",
        content: text,
        client_turn_id: turnId,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);

      try {
        await createTurn(conversationId, text, turnId);
      } catch (err) {
        setBusy(false);
        setError(err instanceof Error ? err.message : "Failed to send message");
      }
    },
    [busy, conversationId],
  );

  return (
    <div className="relative flex min-h-screen min-h-dvh flex-col">
      <div className="pointer-events-none absolute inset-0 grain opacity-70" aria-hidden />

      <header className="sticky top-0 z-20 border-b border-ink-200/60 bg-white/70 backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-3 px-4 py-3.5 sm:py-4">
          <div className="min-w-0">
            <p className="font-display text-2xl tracking-tight text-ink-900 sm:text-[1.75rem]">
              Loopp Support
            </p>
            <p className="mt-0.5 text-xs text-ink-700/60">Customer care · chat & voice</p>
          </div>
          <div
            className={`inline-flex max-w-[55%] items-center gap-2 truncate rounded-full px-3 py-1.5 text-[11px] font-medium sm:max-w-none ${
              healthOk ? "bg-accent-soft text-accent-deep" : "bg-coral-soft text-coral"
            }`}
            title={healthLabel}
          >
            <span
              className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                healthOk ? "bg-accent" : "bg-coral"
              }`}
            />
            <span className="truncate">{healthLabel}</span>
          </div>
        </div>
      </header>

      <main className="relative z-10 flex min-h-0 flex-1 flex-col">
        {booting ? (
          <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 py-10">
            <div className="rounded-[1.75rem] border border-ink-200/70 bg-white/70 p-8 shadow-soft backdrop-blur">
              <div className="skeleton-bar h-3 w-40" />
              <div className="skeleton-bar mt-4 h-3 w-full" />
              <div className="skeleton-bar mt-2 h-3 w-4/5" />
              <p className="mt-6 text-sm text-ink-700/60">Starting your support session…</p>
            </div>
          </div>
        ) : (
          <MessageList
            messages={messages}
            streamingText={streamingText || undefined}
            busy={busy}
            onSuggestion={conversationId && !busy ? (text) => void onSend(text) : undefined}
          />
        )}

        <div className="dock sticky bottom-0 z-20 border-t border-ink-200/50 pt-2">
          <ToolStatus items={toolItems} />
          <VoiceControls
            conversationId={conversationId}
            sessionToken={sessionToken}
            disabled={busy || booting}
            onUserTranscript={(text) => {
              if (!text) return;
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
              setBusy(false);
            }}
            onError={setError}
            onMetric={(metric) => setMetrics((prev) => [...prev, metric as ObsMetric])}
          />
          {error ? (
            <div className="mx-auto flex w-full max-w-3xl items-start justify-between gap-3 px-4 pb-2">
              <p className="rounded-xl border border-coral/20 bg-coral-soft/80 px-3 py-2 text-sm text-coral">
                {error}
              </p>
              <button
                type="button"
                onClick={() => setError(null)}
                className="shrink-0 rounded-lg px-2 py-1 text-xs font-medium text-ink-700/60 hover:bg-white/70"
              >
                Dismiss
              </button>
            </div>
          ) : null}
          <Composer
            disabled={!conversationId || booting}
            busy={busy}
            onSend={onSend}
          />
          <ObservabilityDrawer
            open={obsOpen}
            onToggle={() => setObsOpen((v) => !v)}
            traces={traces}
            metrics={metrics}
          />
        </div>
      </main>
    </div>
  );
}
