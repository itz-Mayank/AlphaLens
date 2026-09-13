import { apiClient } from "@/lib/api-client";

import type { ForecastExplanationResponse, ForecastResponse } from "./types";

export function getForecast(ticker: string) {
  return apiClient.get<ForecastResponse>(`/stocks/${encodeURIComponent(ticker)}/forecast`);
}

export function getForecastExplanation(ticker: string, topN = 5) {
  return apiClient.get<ForecastExplanationResponse>(
    `/stocks/${encodeURIComponent(ticker)}/forecast/explanation?top_n=${topN}`,
  );
}
