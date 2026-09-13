import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Card } from "@/components/Card";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { SignalBadge } from "@/components/SignalBadge";
import { Skeleton } from "@/components/Skeleton";
import { TextField } from "@/components/Field";
import { getForecast } from "@/features/forecast/api";
import { ApiError } from "@/lib/api-client";
import { formatChangePercent, formatPrice } from "@/lib/format";

import { addWatchlistItem, getWatchlist, removeWatchlistItem } from "./api";
import type { WatchlistItem } from "./types";

const KNOWN_ERROR_MESSAGES: Record<string, string> = {
  STOCK_NOT_FOUND: "That ticker isn't known to this deployment yet.",
  WATCHLIST_NOT_FOUND: "This watchlist doesn't exist or isn't yours.",
};

// AI signal enrichment is one extra /forecast call per row — the backend's
// watchlist-detail endpoint batches quotes only, not forecast/sentiment (a
// deliberate scope decision; see watchlist_service.py). Bounding it here
// keeps that N+1 small and real rather than "hundreds of requests" on a
// large list — past this size we just omit the column honestly.
const AI_SIGNAL_MAX_ITEMS = 15;

export function WatchlistDetailPage() {
  const { watchlistId } = useParams<{ watchlistId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [ticker, setTicker] = useState("");

  const watchlistQuery = useQuery({
    queryKey: ["watchlists", watchlistId],
    queryFn: () => getWatchlist(watchlistId as string),
    enabled: Boolean(watchlistId),
  });

  const items = watchlistQuery.data?.items ?? [];
  const showSignals = items.length > 0 && items.length <= AI_SIGNAL_MAX_ITEMS;

  const signalQueries = useQueries({
    queries: showSignals
      ? items.map((item) => ({
          queryKey: ["forecast", item.ticker],
          queryFn: () => getForecast(item.ticker),
          staleTime: 60_000,
          retry: false,
        }))
      : [],
  });
  const signalByTicker = new Map(
    items.map((item, i) => [item.ticker, showSignals ? signalQueries[i] : undefined]),
  );

  const addMutation = useMutation({
    mutationFn: () => addWatchlistItem(watchlistId as string, ticker.trim().toUpperCase()),
    onSuccess: () => {
      setTicker("");
      queryClient.invalidateQueries({ queryKey: ["watchlists", watchlistId] });
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    },
  });

  const removeMutation = useMutation({
    mutationFn: (t: string) => removeWatchlistItem(watchlistId as string, t),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlists", watchlistId] });
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    },
  });

  if (watchlistQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (watchlistQuery.isError) {
    const error = watchlistQuery.error;
    if (error instanceof ApiError && error.status === 404) {
      return <ErrorState message="This watchlist doesn't exist or isn't yours." />;
    }
    return <ErrorState onRetry={() => watchlistQuery.refetch()} />;
  }

  const watchlist = watchlistQuery.data;
  if (!watchlist) return null;

  const addError = addMutation.error;
  const addErrorMessage =
    addError instanceof ApiError ? (KNOWN_ERROR_MESSAGES[addError.code] ?? addError.message) : null;

  const columns: DataTableColumn<WatchlistItem>[] = [
    { key: "ticker", header: "Ticker", render: (r) => <span className="font-medium">{r.ticker}</span> },
    { key: "name", header: "Name", render: (r) => <span className="text-muted">{r.name}</span> },
    {
      key: "price",
      header: "Price",
      align: "right",
      render: (r) => (r.data_unavailable ? <span className="text-muted">No data yet</span> : formatPrice(r.last_price)),
    },
    {
      key: "change",
      header: "Change",
      align: "right",
      render: (r) => {
        if (r.data_unavailable) return <span className="text-muted">—</span>;
        const change = formatChangePercent(r.change_percent);
        return <span className={change.tone}>{change.text}</span>;
      },
    },
    ...(showSignals
      ? [
          {
            key: "signal",
            header: "AI Signal",
            render: (r: WatchlistItem) => {
              const signalQuery = signalByTicker.get(r.ticker);
              if (!signalQuery || signalQuery.isLoading) return <span className="text-muted text-xs">…</span>;
              if (!signalQuery.data) return <SignalBadge direction={null} />;
              return <SignalBadge direction={signalQuery.data.predicted_direction} />;
            },
          } satisfies DataTableColumn<WatchlistItem>,
        ]
      : []),
    {
      key: "freshness",
      header: "Freshness",
      align: "right",
      render: (r) => <DataFreshnessBadge timestamp={r.as_of} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (r) => (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            removeMutation.mutate(r.ticker);
          }}
          disabled={removeMutation.isPending}
          className="text-xs text-muted hover:text-bearish disabled:opacity-50"
        >
          Remove
        </button>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={watchlist.name}
        description={watchlist.description ?? undefined}
        meta={
          <button
            type="button"
            onClick={() => navigate("/app/watchlists")}
            className="text-xs text-muted hover:text-foreground"
          >
            ← All watchlists
          </button>
        }
      />

      <Card className="flex flex-wrap items-end gap-3 p-4">
        <TextField
          label="Add ticker"
          className="min-w-[160px] flex-1 uppercase"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="AAPL"
        />
        <button
          type="button"
          onClick={() => addMutation.mutate()}
          disabled={!ticker.trim() || addMutation.isPending}
          className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
        >
          {addMutation.isPending ? "Adding…" : "Add to watchlist"}
        </button>
        {addErrorMessage && <p className="w-full text-sm text-bearish">{addErrorMessage}</p>}
      </Card>

      {!showSignals && items.length > AI_SIGNAL_MAX_ITEMS && (
        <p className="text-xs text-muted">
          AI signals are shown for watchlists of up to {AI_SIGNAL_MAX_ITEMS} stocks — this list has{" "}
          {items.length}.
        </p>
      )}

      {items.length === 0 ? (
        <EmptyState title="No stocks yet" description="Add a ticker above to start tracking it here." />
      ) : (
        <Card className="overflow-hidden p-0">
          <DataTable
            columns={columns}
            rows={items}
            rowKey={(r) => r.security_id}
            onRowClick={(r) => navigate(`/app/stocks/${r.ticker}`)}
          />
        </Card>
      )}
    </div>
  );
}
