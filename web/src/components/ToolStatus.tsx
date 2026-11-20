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
};

export function ToolStatus({ items }: Props) {
  if (items.length === 0) return null;

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-2">
      <div className="rounded-2xl border border-ink-200/70 bg-white/80 p-3.5 shadow-soft backdrop-blur">
        <div className="mb-3 flex items-center justify-between gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-700/55">
            Live agent steps
          </p>
          <span className="rounded-full bg-ink-50 px-2 py-0.5 text-[10px] font-medium text-ink-700/60">
            {items.length} step{items.length === 1 ? "" : "s"}
          </span>
        </div>
        <ol className="relative space-y-0">
          {items.map((item, index) => {
            const label = LABELS[item.tool] ?? item.tool;
            const isLast = index === items.length - 1;
            return (
              <li key={item.id} className="relative flex gap-3 pb-3 last:pb-0">
                {!isLast ? (
                  <span className="absolute left-[7px] top-4 h-[calc(100%-8px)] w-px bg-ink-100" />
                ) : null}
                <span
                  className={`relative z-[1] mt-1.5 h-3.5 w-3.5 shrink-0 rounded-full border-2 ${
                    item.status === "started"
                      ? "animate-pulse border-amber-400 bg-amber-100"
                      : item.status === "completed"
                        ? "border-accent bg-accent"
                        : "border-coral bg-coral"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <p
                    className={`text-sm font-medium ${
                      item.status === "failed"
                        ? "text-coral"
                        : item.status === "completed"
                          ? "text-ink-900"
                          : "text-ink-700"
                    }`}
                  >
                    {label}
                    <span className="ml-2 text-[11px] font-medium uppercase tracking-wide text-ink-700/45">
                      {item.status}
                    </span>
                  </p>
                  {item.detail ? (
                    <p className="mt-0.5 text-xs text-ink-700/65">{item.detail}</p>
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
