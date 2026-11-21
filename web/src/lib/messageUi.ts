/** UI helpers driven by backend `message.meta.ui` (structured), not reply regex. */

export type MessageCardKind = "refund" | "escalation" | "confirm" | null;

export type ConfirmationUi = {
  kind: "refund";
  invoice_id: string;
  amount_cents: number;
  currency?: string;
  amount_display?: string;
  requires_explicit_confirm?: boolean;
};

export type EscalationUi = {
  ticket_id: string;
  status?: string;
};

export type AssistantUi = {
  confirmation?: ConfirmationUi;
  escalation?: EscalationUi;
  refund_receipt?: Record<string, unknown>;
};

export function assistantUiFromMeta(meta: Record<string, unknown> | undefined | null): AssistantUi {
  if (!meta || typeof meta !== "object") return {};
  const raw = meta.ui;
  if (!raw || typeof raw !== "object") return {};
  return raw as AssistantUi;
}

/** @deprecated Prefer assistantUiFromMeta — kept for non-meta legacy messages only as null. */
export function classifyAssistantMessage(_content: string): MessageCardKind {
  return null;
}

export function extractAmountHint(ui: AssistantUi): string | null {
  return ui.confirmation?.amount_display ?? null;
}

export function extractInvoiceHint(ui: AssistantUi): string | null {
  return ui.confirmation?.invoice_id ?? null;
}
