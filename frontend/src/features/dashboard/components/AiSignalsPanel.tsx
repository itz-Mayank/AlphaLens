import { useQueries } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";
import { SignalBadge } from "@/components/SignalBadge";
import { getForecast } from "@/features/forecast/api";
import type { PredictedDirection } from "@/features/forecast/types";
import { formatPercent } from "@/lib/format";

const DIRECTIONS: PredictedDirection[] = ["Bullish", "Neutral", "Bearish"];
const DIRECTION_BAR_CLASS: Record<PredictedDirection, string> = {
  Bullish: "bg-bullish",
  Neutral: "bg-border",
  Bearish: "bg-bearish",
};

/** Real per-ticker XGBoost forecasts for the securities already surfacing as
 * today's movers — not a market-wide "AI opportunity score" (no such thing
 * exists in the backend), just an honest signal-distribution summary over a
 * small, visible, already-relevant set of tickers. A forecast call failing
 * for one ticker (e.g. insufficient history) silently drops it from the
 * distribution rather than counting it as anything. */
export function AiSignalsPanel({ tickers }: { tickers: string[] }) {
  const results = useQueries({
    queries: tickers.map((ticker) => ({
      queryKey: ["forecast", ticker],
      queryFn: () => getForecast(ticker),
      staleTime: 60_000,
      retry: false,
    })),
  });

  const isLoading = results.some((r) => r.isLoading);
  const available = results
    .map((r) => r.data)
    .filter((d): d is NonNullable<typeof d> => Boolean(d));

  if (isLoading) {
    return (
      <Card className="p-4">
        <Skeleton className="h-24 w-full" />
      </Card>
    );
  }

  if (available.length === 0) {
    return (
      <EmptyState
        title="No AI signals available"
        description="Forecasts for today's tracked movers could not be computed — usually insufficient price history."
      />
    );
  }

  const counts: Record<PredictedDirection, number> = { Bullish: 0, Neutral: 0, Bearish: 0 };
  for (const f of available) counts[f.predicted_direction] += 1;
  const total = available.length;

  return (
    <Card className="p-4">
      <div className="flex h-2.5 overflow-hidden rounded-full bg-border/40">
        {DIRECTIONS.map((d) => (
          <div
            key={d}
            className={DIRECTION_BAR_CLASS[d]}
            style={{ width: `${(counts[d] / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
        {DIRECTIONS.map((d) => (
          <span key={d}>
            <span className="font-medium text-foreground">{counts[d]}</span> {d.toLowerCase()}
          </span>
        ))}
        <span>
          of {total} tracked mover{total === 1 ? "" : "s"} with a computed forecast
        </span>
      </div>
      <ul className="mt-3 divide-y divide-border/60">
        {available.map((f) => (
          <SignalRow key={f.ticker} ticker={f.ticker} direction={f.predicted_direction} expectedReturn={f.expected_return} />
        ))}
      </ul>
    </Card>
  );
}

function SignalRow({
  ticker,
  direction,
  expectedReturn,
}: {
  ticker: string;
  direction: PredictedDirection;
  expectedReturn: number | null;
}) {
  const navigate = useNavigate();
  return (
    <li>
      <button
        type="button"
        onClick={() => navigate(`/app/stocks/${ticker}`)}
        className="flex w-full items-center justify-between gap-3 py-1.5 text-left text-sm hover:bg-border/20"
      >
        <span className="font-medium text-foreground">{ticker}</span>
        <span className="flex items-center gap-2 tabular-nums">
          <span className="text-muted">{expectedReturn !== null ? formatPercent(expectedReturn * 100) : "—"}</span>
          <SignalBadge direction={direction} />
        </span>
      </button>
    </li>
  );
}
