import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Card } from "@/components/Card";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { DemoDataBanner } from "@/components/DemoDataBanner";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MetricCard } from "@/components/MetricCard";
import { Skeleton, SkeletonMetricCards } from "@/components/Skeleton";
import { Tabs } from "@/components/Tabs";
import { ForecastCard } from "@/features/forecast/ForecastCard";
import { TechnicalsPanel } from "@/features/forecast/components/TechnicalsPanel";
import { NewsPanel } from "@/features/news/NewsPanel";
import { SentimentCard } from "@/features/news/SentimentCard";
import { WatchlistQuickAdd } from "@/features/watchlist/components/WatchlistQuickAdd";
import { ApiError } from "@/lib/api-client";
import { formatChangePercent, formatPrice } from "@/lib/format";

import { getStockDetail, getStockPrices } from "./api";
import { PriceChart } from "./components/PriceChart";
import type { PriceRange } from "./types";

const RANGES: PriceRange[] = ["1M", "3M", "6M", "1Y", "5Y", "MAX"];
const TABS = [
  { key: "overview", label: "Overview" },
  { key: "forecast", label: "AI Forecast" },
  { key: "technicals", label: "Technicals" },
  { key: "news", label: "News & Sentiment" },
];

export function StockDetailPage() {
  const { ticker = "" } = useParams<{ ticker: string }>();
  const [range, setRange] = useState<PriceRange>("1Y");
  const [tab, setTab] = useState("overview");

  const detailQuery = useQuery({
    queryKey: ["stocks", "detail", ticker],
    queryFn: () => getStockDetail(ticker),
    retry: false,
  });

  const pricesQuery = useQuery({
    queryKey: ["stocks", "prices", ticker, range],
    queryFn: () => getStockPrices(ticker, range),
    enabled: detailQuery.isSuccess,
  });

  if (detailQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-20 w-full" />
        <SkeletonMetricCards />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (detailQuery.isError) {
    const isNotFound = detailQuery.error instanceof ApiError && detailQuery.error.status === 404;
    if (isNotFound) {
      return (
        <EmptyState
          title={`No data for "${ticker.toUpperCase()}"`}
          description="This ticker hasn't been ingested yet."
          action={
            <Link to="/app/stocks" className="text-sm text-primary hover:underline">
              Back to Stock Explorer
            </Link>
          }
        />
      );
    }
    return <ErrorState onRetry={() => detailQuery.refetch()} />;
  }

  const detail = detailQuery.data;
  if (!detail) return null;

  const change = formatChangePercent(detail.change_percent);
  const isDemo = detail.data_source === "demo";

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link to="/app/stocks" className="text-sm text-muted hover:text-foreground">
          ← Stock Explorer
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-baseline gap-3">
              <h1 className="text-2xl font-semibold tracking-tight">{detail.ticker}</h1>
              <span className="text-muted">{detail.name}</span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
              {detail.sector && <span>{detail.sector}</span>}
              <span className="capitalize">{detail.data_source} data</span>
              <DataFreshnessBadge timestamp={detail.as_of} />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <WatchlistQuickAdd ticker={detail.ticker} />
            <Link
              to="/app/alerts"
              className="rounded border border-border px-2.5 py-1.5 text-sm text-muted hover:text-foreground"
            >
              Create alert
            </Link>
          </div>
        </div>
      </div>

      {isDemo && <DemoDataBanner />}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricCard label="Price" value={formatPrice(detail.last_price)} />
        <MetricCard label="Change" value={change.text} tone={change.tone} />
        <MetricCard label="52W High" value={formatPrice(detail.week_52_high)} />
        <MetricCard label="52W Low" value={formatPrice(detail.week_52_low)} />
      </div>

      <Tabs items={TABS} active={tab} onChange={setTab} />

      {tab === "overview" && (
        <div className="flex flex-col gap-4">
          <div className="flex gap-1.5">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRange(r)}
                className={
                  r === range
                    ? "rounded bg-primary px-2.5 py-1 text-xs font-medium text-white"
                    : "rounded border border-border px-2.5 py-1 text-xs text-muted hover:text-foreground"
                }
              >
                {r}
              </button>
            ))}
          </div>

          {pricesQuery.isLoading && <Skeleton className="h-96 w-full" />}
          {pricesQuery.isError && <ErrorState onRetry={() => pricesQuery.refetch()} />}
          {pricesQuery.isSuccess && pricesQuery.data.bars.length === 0 && (
            <EmptyState title="No price history" description="No bars are available for this range." />
          )}
          {pricesQuery.isSuccess && pricesQuery.data.bars.length > 0 && (
            <Card className="p-4">
              <PriceChart bars={pricesQuery.data.bars} />
            </Card>
          )}
        </div>
      )}

      {tab === "forecast" && <ForecastCard ticker={detail.ticker} />}

      {tab === "technicals" && <TechnicalsPanel ticker={detail.ticker} />}

      {tab === "news" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SentimentCard ticker={detail.ticker} />
          <NewsPanel ticker={detail.ticker} />
        </div>
      )}
    </div>
  );
}
