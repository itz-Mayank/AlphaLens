import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { discoverSecurities, ingestTicker, listStocks } from "@/features/stocks/api";
import type { SecurityDiscoveryResult } from "@/features/stocks/types";
import { formatChangePercent, formatPrice } from "@/lib/format";
import { useAuthStore } from "@/stores/authStore";

/** Global ticker/company search. Two tiers, both real:
 * - "tracked" results come from GET /stocks?q= (securities already
 *   ingested, with real price data).
 * - "discover" results come from GET /stocks/discover — a live pass
 *   through to the configured market-data provider's own symbol search
 *   (real Twelve Data lookups when configured; Demo Mode's fixed list
 *   otherwise) — so searching for a ticker AlphaLens has never tracked
 *   before (e.g. "AMD") surfaces a real match instead of nothing. */
export function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const debounced = useDebouncedValue(query, 250);
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const role = useAuthStore((s) => s.user?.role);
  const canIngest = role === "ANALYST" || role === "ADMIN";

  const trackedQuery = useQuery({
    queryKey: ["stocks", "search", debounced],
    queryFn: () => listStocks({ q: debounced, limit: 8 }),
    enabled: debounced.trim().length > 0,
    staleTime: 30_000,
  });

  const discoverQuery = useQuery({
    queryKey: ["stocks", "discover", debounced],
    queryFn: () => discoverSecurities(debounced, 8),
    enabled: debounced.trim().length >= 2,
    staleTime: 30_000,
    retry: false,
  });

  const ingestMutation = useMutation({
    mutationFn: (ticker: string) => ingestTicker(ticker),
    onSuccess: (_data, ticker) => {
      queryClient.invalidateQueries({ queryKey: ["stocks"] });
      setQuery("");
      setOpen(false);
      navigate(`/app/stocks/${ticker}`);
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

  function select(ticker: string) {
    setQuery("");
    setOpen(false);
    navigate(`/app/stocks/${ticker}`);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      e.currentTarget.blur();
    } else if (e.key === "Enter") {
      const first = trackedQuery.data?.items[0];
      if (first) select(first.ticker);
    }
  }

  const tracked = trackedQuery.data?.items ?? [];
  const trackedTickers = new Set(tracked.map((t) => t.ticker));
  const newDiscoveries: SecurityDiscoveryResult[] = (discoverQuery.data ?? []).filter(
    (d) => !d.already_tracked && !trackedTickers.has(d.ticker),
  );
  const showDropdown = open && debounced.trim().length > 0;
  const isLoading = trackedQuery.isLoading || discoverQuery.isLoading;
  const nothingFound =
    !isLoading && tracked.length === 0 && newDiscoveries.length === 0 && !discoverQuery.isError;

  return (
    <div ref={containerRef} className="relative w-full max-w-xs">
      <input
        type="search"
        role="combobox"
        aria-expanded={showDropdown}
        aria-label="Search securities by ticker or company name"
        placeholder="Search ticker or company…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        className="w-full rounded border border-border bg-transparent px-2.5 py-1.5 text-sm text-foreground outline-none placeholder:text-muted focus:border-primary"
      />
      {showDropdown && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-96 overflow-y-auto rounded border border-border bg-surface shadow-lg">
          {isLoading && <div className="px-3 py-2 text-sm text-muted">Searching…</div>}
          {nothingFound && (
            <div className="px-3 py-2 text-sm text-muted">No securities match "{debounced}".</div>
          )}
          {tracked.map((item) => {
            const change = formatChangePercent(item.change_percent);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => select(item.ticker)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-border/30"
              >
                <span className="min-w-0">
                  <span className="font-medium text-foreground">{item.ticker}</span>
                  <span className="ml-2 truncate text-muted">{item.name}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2 tabular-nums">
                  <span className="text-foreground">{formatPrice(item.last_price)}</span>
                  <span className={change.tone}>{change.text}</span>
                </span>
              </button>
            );
          })}

          {newDiscoveries.length > 0 && (
            <>
              <div className="border-t border-border px-3 py-1 text-[10px] font-medium uppercase tracking-wide text-muted">
                Discover — not yet tracked
              </div>
              {newDiscoveries.map((d) => (
                <div
                  key={d.ticker}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  <span className="min-w-0">
                    <span className="font-medium text-foreground">{d.ticker}</span>
                    <span className="ml-2 truncate text-muted">{d.name}</span>
                    <span className="ml-2 text-xs text-muted">{d.exchange}</span>
                  </span>
                  {canIngest ? (
                    <button
                      type="button"
                      onClick={() => ingestMutation.mutate(d.ticker)}
                      disabled={ingestMutation.isPending}
                      className="shrink-0 rounded border border-primary/40 px-2 py-1 text-xs text-primary hover:bg-primary/10 disabled:opacity-60"
                    >
                      {ingestMutation.isPending && ingestMutation.variables === d.ticker
                        ? "Adding…"
                        : "Add & Research"}
                    </button>
                  ) : (
                    <span className="shrink-0 text-xs text-muted">Ask an analyst to add</span>
                  )}
                </div>
              ))}
            </>
          )}

          {discoverQuery.isError && (
            <div className="border-t border-border px-3 py-2 text-xs text-muted">
              Live discovery is unavailable right now.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
