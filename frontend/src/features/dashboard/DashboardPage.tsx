import { useQuery } from "@tanstack/react-query";

import { DemoDataBanner } from "@/components/DemoDataBanner";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { SectionHeader } from "@/components/SectionHeader";
import { Skeleton, SkeletonMetricCards } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { formatRelativeTime } from "@/lib/format";
import { useAuthStore } from "@/stores/authStore";

import { ProviderStatusPanel } from "@/features/model-lab/components/ProviderStatusPanel";

import { getDashboardOverview } from "./api";
import { AiSignalsPanel } from "./components/AiSignalsPanel";
import { BreadthBar } from "./components/BreadthBar";
import { MoversPanel } from "./components/MoversPanel";
import { RecentActivityList } from "./components/RecentActivityList";
import { SectorBars } from "./components/SectorBars";
import { SummaryCards } from "./components/SummaryCards";

export function DashboardPage() {
  const user = useAuthStore((s) => s.user);

  const query = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: getDashboardOverview,
  });

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-16 w-full" />
        <SkeletonMetricCards />
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-56 lg:col-span-2" />
          <Skeleton className="h-56" />
        </div>
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (query.isError) {
    return <ErrorState message="Unable to load the market overview." onRetry={() => query.refetch()} />;
  }

  const overview = query.data;
  if (!overview) return null;

  const { market_summary, market_movers, sector_overview, market_breadth, recent_activity } = overview;
  const showsDemoData = market_summary.data_sources.includes("demo");

  // A small, honest sample for the AI Signals panel — the movers already
  // rendered on this page, deduped, capped so the dashboard never issues an
  // unbounded number of forecast calls.
  const signalTickers = Array.from(
    new Set([
      ...market_movers.top_gainers.map((m) => m.ticker),
      ...market_movers.top_losers.map((m) => m.ticker),
    ]),
  ).slice(0, 8);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Market Overview"
        description={`Welcome back${user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}. Here's what's happening across tracked securities.`}
        meta={
          <>
            <StatusBadge status={market_summary.freshness_status} />
            {showsDemoData && <StatusBadge status="demo" label="Demo data" />}
            {market_summary.latest_market_data_ts && (
              <span className="text-xs text-muted">
                Last updated {formatRelativeTime(market_summary.latest_market_data_ts)}
              </span>
            )}
          </>
        }
      />

      {showsDemoData && <DemoDataBanner />}

      <SummaryCards summary={market_summary} />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <section>
            <SectionHeader title="Market Movers" />
            <MoversPanel
              topGainers={market_movers.top_gainers}
              topLosers={market_movers.top_losers}
              mostActive={market_movers.most_active}
            />
          </section>

          <section>
            <SectionHeader title="Sector Performance" />
            <SectorBars sectors={sector_overview.sectors} />
          </section>
        </div>

        <div className="flex flex-col gap-6">
          <section>
            <SectionHeader
              title="AI Signals"
              description="XGBoost forecasts for today's tracked movers."
            />
            <AiSignalsPanel tickers={signalTickers} />
          </section>

          <section>
            <SectionHeader title="Market Breadth" />
            <BreadthBar breadth={market_breadth} />
          </section>

          {(user?.role === "ANALYST" || user?.role === "ADMIN") && (
            <section>
              <SectionHeader title="Data Providers" description="Visible to analysts and admins." />
              <ProviderStatusPanel />
            </section>
          )}
        </div>
      </div>

      <section>
        <SectionHeader title="Recently Updated" />
        <RecentActivityList items={recent_activity} />
      </section>
    </div>
  );
}
