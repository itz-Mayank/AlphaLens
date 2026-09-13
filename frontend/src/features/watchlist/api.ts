import { apiClient } from "@/lib/api-client";

import type { Watchlist, WatchlistDetail, WatchlistListItem } from "./types";

export function listWatchlists() {
  return apiClient.get<WatchlistListItem[]>("/watchlists");
}

export function getWatchlist(watchlistId: string) {
  return apiClient.get<WatchlistDetail>(`/watchlists/${watchlistId}`);
}

export function createWatchlist(data: { name: string; description?: string }) {
  return apiClient.post<Watchlist>("/watchlists", data);
}

export function deleteWatchlist(watchlistId: string) {
  return apiClient.delete<void>(`/watchlists/${watchlistId}`);
}

export function addWatchlistItem(watchlistId: string, ticker: string) {
  return apiClient.post<WatchlistDetail>(`/watchlists/${watchlistId}/items`, { ticker });
}

export function removeWatchlistItem(watchlistId: string, ticker: string) {
  return apiClient.delete<void>(`/watchlists/${watchlistId}/items/${encodeURIComponent(ticker)}`);
}
