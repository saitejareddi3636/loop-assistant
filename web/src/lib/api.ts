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

export type RetryFailedRunResponse = {
  conversation_id: string;
  run_id: string;
  failed_run_id: string;
  client_retry_id: string;
  status: string;
  source: string;
  reused: boolean;
};

export function retryFailedRun(
  conversationId: string,
  failedRunId: string,
  clientRetryId: string,
): Promise<RetryFailedRunResponse> {
  return request<RetryFailedRunResponse>(
    `/api/conversations/${conversationId}/runs/${failedRunId}/retry`,
    {
      method: "POST",
      body: JSON.stringify({ client_retry_id: clientRetryId }),
    },
  );
}

export function cancelPendingConfirmation(conversationId: string): Promise<{ cancelled: boolean }> {
  return request(`/api/conversations/${conversationId}/confirmation/cancel`, {
    method: "POST",
    body: JSON.stringify({}),
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

export type TranscribeResult = {
  text: string;
  stt_ms: number;
  stt_provider: string;
  sample_rate: number;
  duration_ms: number;
};

/** Dictation-only STT — does not create messages or run the agent. */
export async function transcribeAudio(
  conversationId: string,
  sessionToken: string,
  wav: Blob,
  sampleRate = 16000,
): Promise<TranscribeResult> {
  const body = new FormData();
  body.append("file", wav, "dictation.wav");
  body.append("sample_rate", String(sampleRate));
  const response = await fetch(`/api/conversations/${conversationId}/transcribe`, {
    method: "POST",
    headers: {
      "X-Session-Token": sessionToken,
    },
    body,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Transcription failed (${response.status})`);
  }
  return response.json() as Promise<TranscribeResult>;
}

/** On-demand Pocket TTS for the chat speaker button. */
export async function speakText(
  conversationId: string,
  sessionToken: string,
  text: string,
): Promise<Blob> {
  const response = await fetch(`/api/conversations/${conversationId}/speak`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-Token": sessionToken,
    },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    const errText = await response.text();
    throw new Error(errText || `Speech failed (${response.status})`);
  }
  return response.blob();
}
