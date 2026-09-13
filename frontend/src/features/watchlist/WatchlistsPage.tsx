import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { formatRelativeDate } from "@/lib/format";

import { createWatchlist, deleteWatchlist, listWatchlists } from "./api";

export function WatchlistsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const watchlistsQuery = useQuery({ queryKey: ["watchlists"], queryFn: listWatchlists });

  const createMutation = useMutation({
    mutationFn: () => createWatchlist({ name: name.trim() }),
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (watchlistId: string) => deleteWatchlist(watchlistId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["watchlists"] }),
  });

  const items = watchlistsQuery.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Watchlists" description="Track groups of stocks you care about." />

      <Card className="flex flex-wrap items-end gap-3 p-4">
        <label className="flex flex-1 min-w-[200px] flex-col gap-1 text-sm">
          <span className="text-xs text-muted">New watchlist name</span>
          <input
            className="rounded border border-border bg-transparent px-2 py-1.5"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Core Holdings"
          />
        </label>
        <button
          type="button"
          onClick={() => createMutation.mutate()}
          disabled={!name.trim() || createMutation.isPending}
          className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
        >
          {createMutation.isPending ? "Creating…" : "Create watchlist"}
        </button>
      </Card>

      {watchlistsQuery.isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {watchlistsQuery.isError && <ErrorState onRetry={() => watchlistsQuery.refetch()} />}

      {watchlistsQuery.isSuccess && items.length === 0 && (
        <EmptyState
          title="No watchlists yet"
          description="Create one above to start tracking stocks."
        />
      )}

      {items.length > 0 && (
        <div className="flex flex-col gap-2">
          {items.map((watchlist) => (
            <Card
              key={watchlist.id}
              className="flex cursor-pointer items-center justify-between p-4 hover:bg-border/20"
              onClick={() => navigate(`/app/watchlists/${watchlist.id}`)}
            >
              <div>
                <p className="font-medium">{watchlist.name}</p>
                <p className="text-xs text-muted">
                  {watchlist.item_count} {watchlist.item_count === 1 ? "stock" : "stocks"} · Created{" "}
                  {formatRelativeDate(watchlist.created_at)}
                </p>
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  deleteMutation.mutate(watchlist.id);
                }}
                disabled={deleteMutation.isPending}
                className="rounded border border-border px-2.5 py-1 text-xs text-muted hover:text-bearish disabled:opacity-50"
              >
                Delete
              </button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
