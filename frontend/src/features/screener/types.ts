export interface ScreenerRow {
  security_id: number;
  ticker: string;
  name: string;
  sector: string | null;
  last_price: string | null;
  change_percent: string | null;
  volume: number | null;
  return_20d_percent: number | null;
  rsi_14: number | null;
  forecast_direction: string | null;
  sentiment_score: number | null;
  unavailable_fields: string[];
}

export interface ScreenerResponse {
  items: ScreenerRow[];
  total: number;
  limit: number;
  offset: number;
  forecast_available: boolean;
  forecast_unavailable_reason: string | null;
  disclaimer: string;
}

export interface ScreenerFilters {
  q?: string;
  sector?: string;
  min_price?: number;
  max_price?: number;
  min_change_percent?: number;
  max_change_percent?: number;
  min_return_20d_percent?: number;
  max_return_20d_percent?: number;
  forecast_direction?: string;
  min_sentiment_score?: number;
  sort_by?: "ticker" | "last_price" | "change_percent" | "return_20d_percent" | "volume" | "rsi_14" | "sentiment_score";
  sort_direction?: "asc" | "desc";
  limit?: number;
  offset?: number;
}
