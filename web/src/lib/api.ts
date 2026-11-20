import type { Conversation, ConversationDetail, TurnResponse } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function createConversation(customerId = "cust_pro_001"): Promise<Conversation> {
  return request<Conversation>("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ customer_id: customerId, title: "Billing support" }),
  });
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/api/conversations/${id}`);
}

export function createTurn(
  conversationId: string,
  text: string,
  clientTurnId: string,
): Promise<TurnResponse> {
  return request<TurnResponse>(`/api/conversations/${conversationId}/turns`, {
    method: "POST",
    body: JSON.stringify({ text, client_turn_id: clientTurnId }),
  });
}

export function getHealth(): Promise<{
  status: string;
  database: string;
  llm_configured: boolean;
  model: string;
}> {
  return request("/api/health");
}
