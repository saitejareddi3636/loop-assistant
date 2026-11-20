/** Lightweight UI classifiers for assistant replies — no backend changes. */

export type MessageCardKind = "refund" | "escalation" | "confirm" | null;

export function classifyAssistantMessage(content: string): MessageCardKind {
  const lower = content.toLowerCase();
  if (
    /escalat|human specialist|support ticket|create_ticket|human review/.test(lower)
  ) {
    return "escalation";
  }
  if (/confirm.*(refund|charge)|ready for confirmation|once you confirm/.test(lower)) {
    return "confirm";
  }
  if (/refund|duplicate charge|inv[-\s]?\d+/i.test(content) && /\$|dollar|amount|eligible/.test(lower)) {
    return "refund";
  }
  return null;
}

export function extractInvoiceHint(content: string): string | null {
  const match = content.match(/INV[-\s]?(\d{3,6})/i);
  return match ? `INV-${match[1]}` : null;
}

export function extractAmountHint(content: string): string | null {
  const match = content.match(/\$\s?(\d+(?:\.\d{2})?)/) || content.match(/(\d+)\s*dollars?/i);
  if (!match) return null;
  return match[0].startsWith("$") ? match[0] : `$${match[1]}`;
}
