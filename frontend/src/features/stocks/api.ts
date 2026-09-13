import { apiClient } from "@/lib/api-client";

import type {
  IngestResponse,
  Page,
  PriceHistory,
  PriceRange,
  SecurityDiscoveryResult,
  StockDetail,
  StockListItem,
} from "./types";

export interface ListStocksParams {
  q?: string;
  sector?: string;
  limit?: number;
  offset?: number;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function listStocks(params: ListStocksParams) {
  return apiClient.get<Page<StockListItem>>(
    `/stocks${buildQuery({
      q: params.q,
      sector: params.sector,
      limit: params.limit,
      offset: params.offset,
    })}`,
  );
}

export function getStockDetail(ticker: string) {
  return apiClient.get<StockDetail>(`/stocks/${encodeURIComponent(ticker)}`);
}

export function getStockPrices(ticker: string, range: PriceRange) {
  return apiClient.get<PriceHistory>(
    `/stocks/${encodeURIComponent(ticker)}/prices${buildQuery({ range })}`,
  );
}

/** Live provider-backed discovery (GET /stocks/discover) — distinct from
 * listStocks, which only searches securities already ingested. */
export function discoverSecurities(q: string, limit = 8) {
  return apiClient.get<SecurityDiscoveryResult[]>(
    `/stocks/discover${buildQuery({ q, limit })}`,
  );
}

/** Ingests one specific ticker on demand (ANALYST/ADMIN only) — used when
 * a user selects a discovered-but-not-yet-tracked security. */
export function ingestTicker(ticker: string) {
  return apiClient.post<IngestResponse>("/market-data/ingest", { tickers: [ticker] });
}
