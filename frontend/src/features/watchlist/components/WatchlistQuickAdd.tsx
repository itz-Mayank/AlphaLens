import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "@/lib/api-client";

import { addWatchlistItem, listWatchlists } from "../api";

/** Quick-add a ticker to one of the user's existing watchlists, from the
 * stock detail header. Doesn't pre-check per-watchlist membership (that
 * would mean an extra call per watchlist just to render a button) — a
 * duplicate add simply surfaces the backend's own response. */
export function WatchlistQuickAdd({ ticker }: { ticker: string }) {
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const watchlistsQuery = useQuery({
    queryKey: ["watchlists"],
    queryFn: listWatchlists,
    enabled: open,
    staleTime: 30_000,
  });

  const addMutation = useMutation({
    mutationFn: ({ watchlistId }: { watchlistId: string }) => addWatchlistItem(watchlistId, ticker),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      queryClient.invalidateQueries({ queryKey: ["watchlist", variables.watchlistId] });
      setFeedback({ tone: "ok", text: "Added." });
    },
    onError: (error) => {
      setFeedback({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Couldn't add to watchlist.",
      });
    },
  });

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          setFeedback(null);
        }}
        className="rounded border border-border px-2.5 py-1.5 text-sm text-muted hover:text-foreground"
      >
        + Watchlist
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-56 rounded border border-border bg-surface p-1 shadow-lg">
          {watchlistsQuery.isLoading && <p className="px-2 py-1.5 text-xs text-muted">Loading…</p>}
          {watchlistsQuery.isSuccess && watchlistsQuery.data.length === 0 && (
            <div className="px-2 py-1.5 text-xs text-muted">
              No watchlists yet.{" "}
              <Link to="/app/watchlists" className="text-primary hover:underline">
                Create one
              </Link>
              .
            </div>
          )}
          {watchlistsQuery.data?.map((w) => (
            <button
              key={w.id}
              type="button"
              disabled={addMutation.isPending}
              onClick={() => addMutation.mutate({ watchlistId: w.id })}
              className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm hover:bg-border/30 disabled:opacity-60"
            >
              <span className="truncate">{w.name}</span>
              <span className="text-xs text-muted">{w.item_count}</span>
            </button>
          ))}
          {feedback && (
            <p className={`px-2 py-1 text-xs ${feedback.tone === "ok" ? "text-bullish" : "text-bearish"}`}>
              {feedback.text}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
