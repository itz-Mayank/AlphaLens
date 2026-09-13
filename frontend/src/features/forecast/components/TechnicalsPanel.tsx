import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { SectionHeader } from "@/components/SectionHeader";
import { ApiError } from "@/lib/api-client";
import { toneForSign } from "@/lib/format";

import { getForecastExplanation } from "../api";
import type { FeatureContribution } from "../types";

/** Curated technical-indicator subset of the model's full 27-feature set —
 * excludes calendar features (day_of_week, month, ...) that aren't
 * "technicals" in the conventional sense. Requesting the full feature count
 * (top_n = all features) guarantees each of these is present in the
 * response rather than only whichever features happened to rank in a
 * smaller top-N. Each `format` matches the feature's actual definition in
 * ml/features/*.py — e.g. momentum_10d is a raw dollar price difference
 * (`close.diff(10)`), not a percentage, so it's formatted as currency, not
 * guessed generically as a plain number. */
function formatSignedDollars(v: number): string {
  const sign = v >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

const TECHNICAL_FEATURES: { key: string; label: string; format: (v: number) => string }[] = [
  { key: "rsi_14", label: "RSI (14)", format: (v) => v.toFixed(1) },
  { key: "momentum_10d", label: "Momentum (10D)", format: formatSignedDollars },
  { key: "volatility_20d", label: "Volatility (20D)", format: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "macd_line", label: "MACD Line", format: formatSignedDollars },
  { key: "macd_histogram", label: "MACD Histogram", format: formatSignedDollars },
  { key: "atr_14", label: "ATR (14)", format: (v) => `$${v.toFixed(2)}` },
  { key: "bollinger_percent_b", label: "Bollinger %B", format: (v) => `${(v * 100).toFixed(1)}%` },
  { key: "relative_volume_20", label: "Relative Volume (20D)", format: (v) => `${v.toFixed(2)}×` },
  { key: "price_to_sma_20", label: "Price vs SMA(20)", format: (v) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%` },
];

const FULL_FEATURE_COUNT = 27;

interface TechnicalsPanelProps {
  ticker: string;
}

export function TechnicalsPanel({ ticker }: TechnicalsPanelProps) {
  const query = useQuery({
    queryKey: ["forecast", "explanation", ticker, "full"],
    queryFn: () => getForecastExplanation(ticker, FULL_FEATURE_COUNT),
    retry: false,
  });

  if (query.isLoading) {
    return (
      <Card className="p-4">
        <Skeleton className="h-48 w-full" />
      </Card>
    );
  }

  if (query.isError) {
    const knownUnavailable = query.error instanceof ApiError && query.error.status === 422;
    if (knownUnavailable) {
      return (
        <EmptyState
          title="Technicals unavailable"
          description="Not enough price history to compute technical features for this stock yet."
        />
      );
    }
    return <ErrorState onRetry={() => query.refetch()} />;
  }

  const data = query.data;
  if (!data) return null;

  const byFeature = new Map<string, FeatureContribution>();
  for (const factor of [...data.top_return_factors, ...data.top_direction_factors]) {
    byFeature.set(factor.feature, factor);
  }

  const rows = TECHNICAL_FEATURES.map(({ key, label, format }) => ({
    label,
    format,
    factor: byFeature.get(key),
  })).filter((row) => row.factor);

  if (rows.length === 0) {
    return (
      <EmptyState
        title="No technical features available"
        description="The model's explanation output didn't include any of the tracked technical indicators for this stock."
      />
    );
  }

  return (
    <Card className="p-4">
      <SectionHeader
        title="Technicals"
        description={`As of ${data.as_of} — feature set ${data.feature_version}. Contribution direction reflects each feature's current pull on this forecast, from the same SHAP explainer as the AI Forecast tab.`}
      />
      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
        {rows.map(({ label, format, factor }) => (
          <div
            key={label}
            className="flex items-center justify-between border-b border-border/60 pb-2 text-sm"
          >
            <dt className="text-muted">{label}</dt>
            <dd className="flex items-center gap-2 tabular-nums">
              <span className="font-medium text-foreground">{format(factor!.value)}</span>
              <span className={toneForSign(factor!.contribution)} title="Current pull on the forecast">
                {factor!.direction === "positive" ? "▲" : "▼"}
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
