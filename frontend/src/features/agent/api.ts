import { apiClient } from "@/lib/api-client";

import type { ChatRequest, ChatResponse } from "./types";

export function postChat(request: ChatRequest) {
  return apiClient.post<ChatResponse>("/research/chat", request);
}
