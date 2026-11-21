export type Conversation = {
  id: string;
  customer_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  session_token?: string | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  client_turn_id?: string | null;
  run_id?: string | null;
  meta?: Record<string, unknown>;
  created_at: string;
};

export type ConversationDetail = Conversation & {
  messages: ChatMessage[];
};

export type TurnResponse = {
  conversation_id: string;
  run_id: string;
  client_turn_id: string;
  status: string;
};

export type StreamEvent = {
  id?: number;
  sequence: number;
  conversation_id: string;
  run_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at?: string | null;
};

export type ToolStatusItem = {
  id: string;
  tool: string;
  status: "started" | "completed" | "failed" | "awaiting";
  detail?: string;
  at: number;
};

export type ObsMetric = {
  source?: string;
  model?: string;
  prompt_tokens_est?: number;
  completion_tokens_est?: number;
  total_tokens_est?: number;
  estimated_cost_usd?: number;
  stt_latency_ms?: number;
  tts_first_audio_ms?: number;
  interrupt_stop_ms?: number;
  agent_latency_ms?: number;
  [key: string]: unknown;
};
