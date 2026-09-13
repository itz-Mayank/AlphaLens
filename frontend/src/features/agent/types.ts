export interface ChatRequest {
  message: string;
  conversation_id?: string | null;
}

export interface Evidence {
  source_type: string;
  source_id: string;
  ticker: string | null;
  timestamp: string;
  data: Record<string, unknown>;
  provenance: string;
}

export interface ToolCallTrace {
  name: string;
  ok: boolean;
  latency_ms: number;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  evidence: Evidence[];
  citations: string[];
  tools_used: string[];
  tool_calls: ToolCallTrace[];
  model: string;
  provider: string;
  request_id: string;
  prompt_version: string;
  disclaimer: string;
}

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: string[];
  evidence?: Evidence[];
  toolsUsed?: string[];
  toolCalls?: ToolCallTrace[];
}
