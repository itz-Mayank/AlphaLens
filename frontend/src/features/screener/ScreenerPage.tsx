import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Card } from "@/components/Card";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SelectField, TextField } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { SignalBadge } from "@/components/SignalBadge";
import { listStocks } from "@/features/stocks/api";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { formatChangePercent, formatPercent, formatPrice, toneForSign } from "@/lib/format";

import { runScreener } from "./api";
import type { ScreenerFilters, ScreenerRow } from "./types";

const PAGE_SIZE = 25;

const SORT_OPTIONS: { value: NonNullable<ScreenerFilters["sort_by"]>; label: string }[] = [
  { value: "ticker", label: "Ticker" },
  { value: "last_price", label: "Price" },
  { value: "change_percent", label: "Change %" },
  { value: "return_20d_percent", label: "20D Return" },
  { value: "volume", label: "Volume" },
  { value: "rsi_14", label: "RSI (14)" },
  { value: "sentiment_score", label: "Sentiment" },
];

interface FilterState {
  q: string;
  sector: string;
  minPrice: string;
  maxPrice: string;
  minChangePercent: string;
  maxChangePercent: string;
  minReturn20d: string;
  maxReturn20d: string;
  forecastDirection: string;
  minSentiment: string;
}

const EMPTY_FILTERS: FilterState = {
  q: "",
  sector: "",
  minPrice: "",
  maxPrice: "",
  minChangePercent: "",
  maxChangePercent: "",
  minReturn20d: "",
  maxReturn20d: "",
  forecastDirection: "",
  minSentiment: "",
};

function toNumber(value: string): number | undefined {
  if (value.trim() === "") return undefined;
  const n = Number(value);
  return Number.isNaN(n) ? undefined : n;
}

export function ScreenerPage() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [sortBy, setSortBy] = useState<ScreenerFilters["sort_by"]>("ticker");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [offset, setOffset] = useState(0);
  const debouncedSearch = useDebouncedValue(filters.q, 300);

  const sectorOptionsQuery = useQuery({
    queryKey: ["stocks", "sector-options"],
    queryFn: () => listStocks({ limit: 100 }),
    staleTime: 5 * 60_000,
  });
  const sectorOptions = useMemo(() => {
    const sectors = new Set<string>();
    for (const item of sectorOptionsQuery.data?.items ?? []) {
      if (item.sector) sectors.add(item.sector);
    }
    return Array.from(sectors).sort();
  }, [sectorOptionsQuery.data]);

  const queryFilters: ScreenerFilters = {
    q: debouncedSearch || undefined,
    sector: filters.sector || undefined,
    min_price: toNumber(filters.minPrice),
    max_price: toNumber(filters.maxPrice),
    min_change_percent: toNumber(filters.minChangePercent),
    max_change_percent: toNumber(filters.maxChangePercent),
    min_return_20d_percent: toNumber(filters.minReturn20d),
    max_return_20d_percent: toNumber(filters.maxReturn20d),
    forecast_direction: filters.forecastDirection || undefined,
    min_sentiment_score: toNumber(filters.minSentiment),
    sort_by: sortBy,
    sort_direction: sortDirection,
    limit: PAGE_SIZE,
    offset,
  };

  const query = useQuery({
    queryKey: ["screener", queryFilters],
    queryFn: () => runScreener(queryFilters),
  });

  function updateFilter<K extends keyof FilterState>(key: K, value: FilterState[K]) {
    setFilters((f) => ({ ...f, [key]: value }));
    setOffset(0);
  }

  function handleSortChange(key: string) {
    if (key === sortBy) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key as ScreenerFilters["sort_by"]);
      setSortDirection("asc");
    }
    setOffset(0);
  }

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  const columns: DataTableColumn<ScreenerRow>[] = [
    {
      key: "ticker",
      header: "Ticker",
      sortKey: "ticker",
      render: (r) => <span className="font-medium">{r.ticker}</span>,
    },
    { key: "sector", header: "Sector", render: (r) => r.sector ?? "—" },
    {
      key: "price",
      header: "Price",
      align: "right",
      sortKey: "last_price",
      render: (r) => formatPrice(r.last_price),
    },
    {
      key: "change",
      header: "Change",
      align: "right",
      sortKey: "change_percent",
      render: (r) => {
        const change = formatChangePercent(r.change_percent);
        return <span className={change.tone}>{change.text}</span>;
      },
    },
    {
      key: "return20d",
      header: "20D Return",
      align: "right",
      sortKey: "return_20d_percent",
      render: (r) => <span className={toneForSign(r.return_20d_percent)}>{formatPercent(r.return_20d_percent)}</span>,
    },
    {
      key: "rsi",
      header: "RSI(14)",
      align: "right",
      className: "text-muted",
      sortKey: "rsi_14",
      render: (r) => (r.rsi_14 === null ? "—" : r.rsi_14.toFixed(1)),
    },
    {
      key: "forecast",
      header: "Forecast",
      render: (r) => <SignalBadge direction={r.forecast_direction} />,
    },
    {
      key: "sentiment",
      header: "Sentiment",
      align: "right",
      sortKey: "sentiment_score",
      render: (r) =>
        r.sentiment_score === null ? (
          <span className="text-muted">—</span>
        ) : (
          <span className={toneForSign(r.sentiment_score)}>{r.sentiment_score.toFixed(2)}</span>
        ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Screener"
        description="Filter tracked stocks by real price, forecast, and sentiment data from this deployment."
        meta={total > 0 ? <span className="text-xs text-muted">{total} matches</span> : undefined}
      />

      <Card className="flex flex-col gap-3 p-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <TextField
            type="search"
            label="Search"
            value={filters.q}
            onChange={(e) => updateFilter("q", e.target.value)}
            placeholder="Ticker or company…"
          />
          <SelectField
            label="Sector"
            value={filters.sector}
            onChange={(e) => updateFilter("sector", e.target.value)}
          >
            <option value="">All sectors</option>
            {sectorOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="AI Forecast"
            value={filters.forecastDirection}
            onChange={(e) => updateFilter("forecastDirection", e.target.value)}
          >
            <option value="">Any</option>
            <option value="Bullish">Bullish</option>
            <option value="Neutral">Neutral</option>
            <option value="Bearish">Bearish</option>
          </SelectField>
          <TextField
            type="number"
            label="Min price"
            value={filters.minPrice}
            onChange={(e) => updateFilter("minPrice", e.target.value)}
          />
          <TextField
            type="number"
            label="Max price"
            value={filters.maxPrice}
            onChange={(e) => updateFilter("maxPrice", e.target.value)}
          />
          <TextField
            type="number"
            label="Min change %"
            value={filters.minChangePercent}
            onChange={(e) => updateFilter("minChangePercent", e.target.value)}
          />
          <TextField
            type="number"
            label="Max change %"
            value={filters.maxChangePercent}
            onChange={(e) => updateFilter("maxChangePercent", e.target.value)}
          />
          <TextField
            type="number"
            label="Min 20D return %"
            value={filters.minReturn20d}
            onChange={(e) => updateFilter("minReturn20d", e.target.value)}
          />
          <TextField
            type="number"
            label="Max 20D return %"
            value={filters.maxReturn20d}
            onChange={(e) => updateFilter("maxReturn20d", e.target.value)}
          />
          <TextField
            type="number"
            step="0.1"
            min="-1"
            max="1"
            label="Min sentiment"
            value={filters.minSentiment}
            onChange={(e) => updateFilter("minSentiment", e.target.value)}
          />
          <SelectField
            label="Sort by"
            value={sortBy}
            onChange={(e) => handleSortChange(e.target.value)}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </SelectField>
        </div>
        {(filters.q ||
          filters.sector ||
          filters.minPrice ||
          filters.maxPrice ||
          filters.minChangePercent ||
          filters.maxChangePercent ||
          filters.minReturn20d ||
          filters.maxReturn20d ||
          filters.forecastDirection ||
          filters.minSentiment) && (
          <button
            type="button"
            onClick={() => {
              setFilters(EMPTY_FILTERS);
              setOffset(0);
            }}
            className="self-start text-xs text-primary hover:underline"
          >
            Clear filters
          </button>
        )}
      </Card>

      {query.data && !query.data.forecast_available && (
        <p className="rounded border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-warning">
          {query.data.forecast_unavailable_reason ??
            "No forecast model is available right now — forecast columns will be empty."}
        </p>
      )}

      {query.isError && <ErrorState onRetry={() => query.refetch()} />}

      {query.isSuccess && items.length === 0 && (
        <EmptyState
          title="No matching stocks"
          description="Try different filters, or clear them to see the full universe."
        />
      )}

      {(!query.isError && (query.isLoading || items.length > 0)) && (
        <Card className="overflow-hidden p-0">
          <DataTable
            columns={columns}
            rows={items}
            rowKey={(r) => r.security_id}
            onRowClick={(r) => navigate(`/app/stocks/${r.ticker}`)}
            isLoading={query.isLoading}
            sortBy={sortBy}
            sortDirection={sortDirection}
            onSortChange={handleSortChange}
          />
        </Card>
      )}

      {query.isSuccess && total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-muted">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded border border-border px-3 py-1 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="rounded border border-border px-3 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {query.data && <p className="text-xs text-muted">{query.data.disclaimer}</p>}
    </div>
  );
}
