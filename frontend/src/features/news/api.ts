import { apiClient } from "@/lib/api-client";

import type { NewsListResponse, SentimentHistoryResponse, SentimentOverviewResponse } from "./types";

export function getStockNews(ticker: string, limit = 10) {
  return apiClient.get<NewsListResponse>(
    `/stocks/${encodeURIComponent(ticker)}/news?limit=${limit}`,
  );
}

export function getStockSentiment(ticker: string) {
  return apiClient.get<SentimentOverviewResponse>(
    `/stocks/${encodeURIComponent(ticker)}/sentiment`,
  );
}

export function getStockSentimentHistory(ticker: string, days = 30) {
  return apiClient.get<SentimentHistoryResponse>(
    `/stocks/${encodeURIComponent(ticker)}/sentiment/history?days=${days}`,
  );
}
