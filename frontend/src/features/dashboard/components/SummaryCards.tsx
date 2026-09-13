import { MetricCard } from "@/components/MetricCard";
import { StatusBadge } from "@/components/StatusBadge";
import { formatRelativeDate } from "@/lib/format";

import type { MarketSummary } from "../types";

export function SummaryCards({ summary }: { summary: MarketSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <MetricCard label="Tracked securities" value={summary.total_securities} />
      <MetricCard
        label="With price data"
        value={`${summary.securities_with_price_data} / ${summary.total_securities}`}
      />
      <MetricCard
        label="Latest data"
        value={summary.latest_market_data_ts ? formatRelativeDate(summary.latest_market_data_ts) : "—"}
      />
      <MetricCard label="Freshness" value={<StatusBadge status={summary.freshness_status} />} />
    </div>
  );
}
