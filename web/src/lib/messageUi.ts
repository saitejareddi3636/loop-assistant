/** Lightweight UI classifiers for assistant replies — no backend changes. */

export type MessageCardKind = "refund" | "escalation" | "confirm" | null;

export function classifyAssistantMessage(content: string): MessageCardKind {
  const lower = content.toLowerCase();
  if (
    /escalat|human specialist|support ticket|create_ticket|human review/.test(lower)
  ) {
    return "escalation";
  }
  // Only treat as an actionable confirm card when the agent is asking the user
  // to confirm now — not when policy text merely mentions "confirmation".
  if (
    /\b(please confirm|confirm that you|would you like me to|reply\s+[“"']?yes|say\s+[“"']?yes|ready for confirmation|once you confirm)\b/.test(
      lower,
    ) && /\b(refund|charge|invoice)\b/.test(lower)
  ) {
    return "confirm";
  }
  if (
    /\b(refund|duplicate charge)\b/.test(lower) &&
    /inv[-\s]?\d+/i.test(content) &&
    /\$|dollar|amount|eligible/.test(lower) &&
    !/\b(policy|section|citation)\b/.test(lower)
  ) {
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
