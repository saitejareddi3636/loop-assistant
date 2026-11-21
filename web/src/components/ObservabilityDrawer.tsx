import type { ObsMetric } from "../lib/types";

type Props = {
  open: boolean;
  onToggle: () => void;
  traces: string[];
  metrics: ObsMetric[];
  compact?: boolean;
};

export function ObservabilityDrawer({ open, onToggle, traces, metrics, compact }: Props) {
  const latest = metrics[metrics.length - 1];
  const recent = metrics.slice(-4).reverse();
  const panelId = "observability-panel";

  return (
    <div className={compact ? "" : "border-t border-ink-200/60 bg-white/75 backdrop-blur-md"}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={panelId}
        className={`flex w-full items-center justify-between text-left transition hover:bg-ink-50/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          compact ? "rounded-lg px-2 py-2" : "px-4 py-3"
        }`}
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-ink-900">
          <span className="inline-flex h-2 w-2 rounded-full bg-accent" aria-hidden />
          Observability
        </span>
        <span className="rounded-full bg-ink-50 px-2.5 py-1 text-[11px] font-medium text-ink-700/70">
          {open ? "Hide" : "Show"}
        </span>
      </button>

      {open ? (
        <div
          id={panelId}
          className={`grid gap-3 ${compact ? "px-1 pb-1 pt-1" : "border-t border-ink-100 px-4 pb-4 pt-3 md:grid-cols-2"}`}
        >
          <section>
            <p className="mb-1.5 text-xs font-medium text-ink-700/55">Prompt / tool trace</p>
            <ul className="max-h-32 space-y-1 overflow-y-auto rounded-xl bg-ink-50/70 p-2 text-xs text-ink-900">
              {traces.length === 0 ? (
                <li className="px-1 py-2 text-ink-700/45">No events yet.</li>
              ) : null}
              {traces.map((line, i) => (
                <li
                  key={`${i}-${line}`}
                  className="rounded-lg bg-white/80 px-2 py-1.5 font-mono text-[11px] leading-snug text-ink-700"
                >
                  {line}
                </li>
              ))}
            </ul>
          </section>

          <section>
            <p className="mb-1.5 text-xs font-medium text-ink-700/55">Latency & cost</p>
            {latest ? (
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-1.5">
                  <MetricCard label="Tokens" value={String(latest.total_tokens_est ?? "—")} />
                  <MetricCard
                    label="Cost"
                    value={
                      typeof latest.estimated_cost_usd === "number"
                        ? `$${latest.estimated_cost_usd.toFixed(6)}`
                        : "—"
                    }
                  />
                  <MetricCard label="STT" value={fmt(latest.stt_latency_ms)} />
                  <MetricCard label="TTS" value={fmt(latest.tts_first_audio_ms)} />
                </div>
                <p className="text-[11px] text-ink-700/55">
                  Model <span className="font-medium text-ink-900">{latest.model ?? "—"}</span>
                  {latest.source ? (
                    <>
                      {" "}
                      · <span className="font-medium text-ink-900">{latest.source}</span>
                    </>
                  ) : null}
                </p>
                {recent.length > 1 ? (
                  <p className="text-[11px] text-ink-700/45">{recent.length} snapshots</p>
                ) : null}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-ink-200 bg-ink-50/50 px-3 py-3 text-xs text-ink-700/50">
                Metrics appear after a turn completes.
              </div>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-ink-100 bg-white/90 px-2.5 py-2">
      <p className="text-[10px] font-medium text-ink-700/45">{label}</p>
      <p className="mt-0.5 text-sm font-semibold tabular-nums text-ink-900">{value}</p>
    </div>
  );
}

function fmt(ms?: number) {
  return typeof ms === "number" ? `${Math.round(ms)} ms` : "—";
}
