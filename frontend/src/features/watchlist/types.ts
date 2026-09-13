export interface Watchlist {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface WatchlistListItem extends Watchlist {
  item_count: number;
}

export interface WatchlistItem {
  security_id: number;
  ticker: string;
  name: string;
  sector: string | null;
  last_price: string | null;
  change: string | null;
  change_percent: string | null;
  volume: number | null;
  as_of: string | null;
  data_unavailable: boolean;
}

export interface WatchlistDetail extends Watchlist {
  items: WatchlistItem[];
}
