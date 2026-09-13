export type FreshnessStatus = "current" | "stale" | "outdated" | "no_data";
export type BreadthStatus = "ok" | "unavailable";

export interface MarketSummary {
  total_securities: number;
  securities_with_price_data: number;
  latest_market_data_ts: string | null;
  data_sources: string[];
  freshness_status: FreshnessStatus;
}

export interface MoverItem {
  ticker: string;
  name: string;
  sector: string | null;
  last_price: string;
  change_percent: string;
  volume: number;
}

export interface ActiveItem {
  ticker: string;
  name: string;
  sector: string | null;
  last_price: string;
  volume: number;
}

export interface MarketMovers {
  as_of: string | null;
  top_gainers: MoverItem[];
  top_losers: MoverItem[];
  most_active: ActiveItem[];
}

export interface SectorPerformance {
  sector: string;
  security_count: number;
  securities_with_data: number;
  average_return_percent: string | null;
}

export interface SectorOverview {
  as_of: string | null;
  sectors: SectorPerformance[];
}

export interface MarketBreadth {
  as_of: string | null;
  status: BreadthStatus;
  advancing: number | null;
  declining: number | null;
  unchanged: number | null;
  no_data: number;
}

export interface RecentActivityItem {
  ticker: string;
  name: string;
  last_price: string;
  as_of: string;
}

export interface DashboardOverview {
  market_summary: MarketSummary;
  market_movers: MarketMovers;
  sector_overview: SectorOverview;
  market_breadth: MarketBreadth;
  recent_activity: RecentActivityItem[];
}
