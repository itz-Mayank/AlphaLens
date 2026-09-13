export interface StockListItem {
  id: number;
  ticker: string;
  name: string;
  exchange: string;
  sector: string | null;
  industry: string | null;
  currency: string;
  status: string;
  data_source: string;
  last_price: string | null;
  change: string | null;
  change_percent: string | null;
  volume: number | null;
  as_of: string | null;
}

export interface StockDetail extends StockListItem {
  week_52_high: string | null;
  week_52_low: string | null;
}

export interface PriceBar {
  ts: string;
  open: string;
  high: string;
  low: string;
  close: string;
  adjusted_close: string;
  volume: number;
}

export interface PriceHistory {
  ticker: string;
  data_source: string;
  bars: PriceBar[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type PriceRange = "1M" | "3M" | "6M" | "1Y" | "5Y" | "MAX";

export interface SecurityDiscoveryResult {
  ticker: string;
  name: string;
  exchange: string;
  currency: string;
  already_tracked: boolean;
}

export interface IngestResponse {
  job_id: string;
  status: string;
}
