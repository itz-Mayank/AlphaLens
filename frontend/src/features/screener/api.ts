import { apiClient } from "@/lib/api-client";

import type { ScreenerFilters, ScreenerResponse } from "./types";

function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function runScreener(filters: ScreenerFilters) {
  return apiClient.get<ScreenerResponse>(
    `/screener${buildQuery({
      q: filters.q,
      sector: filters.sector,
      min_price: filters.min_price,
      max_price: filters.max_price,
      min_change_percent: filters.min_change_percent,
      max_change_percent: filters.max_change_percent,
      min_return_20d_percent: filters.min_return_20d_percent,
      max_return_20d_percent: filters.max_return_20d_percent,
      forecast_direction: filters.forecast_direction,
      min_sentiment_score: filters.min_sentiment_score,
      sort_by: filters.sort_by,
      sort_direction: filters.sort_direction,
      limit: filters.limit,
      offset: filters.offset,
    })}`,
  );
}
