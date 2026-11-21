import type { ToolStatusItem } from "../lib/types";

const LABELS: Record<string, string> = {
  verify_customer: "Verifying customer identity",
  get_account: "Checking account tier & contract",
  get_invoice: "Looking up invoice",
  search_policy: "Searching support policies",
  issue_mock_refund: "Issuing mock refund",
  create_ticket: "Opening human-review ticket",
};

type Props = {
  items: ToolStatusItem[];
  compact?: boolean;
};

function statusLabel(item: ToolStatusItem): string {
  if (item.status === "awaiting" || item.detail === "confirmation_required") {
    return "Awaiting confirmation";
  }
  if (item.status === "started") return "In progress";
  if (item.status === "completed") return "Done";
  if (item.status === "failed") return "Failed";
  return item.status;
}

function displayLabel(item: ToolStatusItem): string {
  if (item.status === "awaiting" || item.detail === "confirmation_required") {
    return "Awaiting confirmation";
  }
  return LABELS[item.tool] ?? item.tool;
}

export function ToolStatus({ items, compact }: Props) {
  if (items.length === 0) {
    return (
      <div className={compact ? "px-1 py-2" : "mx-auto w-full max-w-3xl px-4 pb-2"}>
        <p className="text-xs text-ink-700/45">Agent steps will appear here during a turn.</p>
      </div>
    );
  }

  return (
    <div
      className={compact ? "" : "mx-auto w-full max-w-3xl px-4 pb-2"}
      aria-live="polite"
      aria-relevant="additions text"
    >
      <div
        className={
          compact
            ? "space-y-0"
            : "rounded-2xl border border-ink-200/70 bg-white/80 p-3.5 shadow-soft backdrop-blur"
        }
      >
        {!compact ? (
          <div className="mb-3 flex items-center justify-between gap-2">
            <p className="text-xs font-semibold text-ink-700/70">Live agent steps</p>
            <span className="rounded-full bg-ink-50 px-2 py-0.5 text-[10px] font-medium text-ink-700/60">
              {items.length} step{items.length === 1 ? "" : "s"}
            </span>
          </div>
        ) : null}
        <ol className="relative space-y-0">
          {items.map((item, index) => {
            const label = displayLabel(item);
            const isLast = index === items.length - 1;
            const awaiting = item.status === "awaiting" || item.detail === "confirmation_required";
            return (
              <li key={item.id} className="relative flex gap-2.5 pb-2.5 last:pb-0">
                {!isLast ? (
                  <span className="absolute left-[6px] top-3.5 h-[calc(100%-6px)] w-px bg-ink-100" />
                ) : null}
                <span
                  className={`relative z-[1] mt-1 h-3 w-3 shrink-0 rounded-full border-2 ${
                    awaiting
                      ? "border-accent bg-accent-soft"
                      : item.status === "started"
                        ? "animate-pulse-dot border-amber-400 bg-amber-100"
                        : item.status === "completed"
                          ? "border-accent bg-accent"
                          : "border-coral bg-coral"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <p
                    className={`text-[13px] font-medium leading-snug ${
                      awaiting
                        ? "text-accent-deep"
                        : item.status === "failed"
                          ? "text-coral"
                          : "text-ink-900"
                    }`}
                  >
                    {label}
                  </p>
                  <p className="mt-0.5 text-[11px] text-ink-700/55">{statusLabel(item)}</p>
                  {item.detail && item.detail !== "confirmation_required" ? (
                    <p className="mt-0.5 text-[11px] text-ink-700/65 break-words">{item.detail}</p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
