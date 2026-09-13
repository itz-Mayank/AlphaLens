import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import clsx from "clsx";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { ApiError } from "@/lib/api-client";
import { formatPercent } from "@/lib/format";

import { getForecast, getForecastExplanation } from "./api";
import { ModelFreshnessNotice } from "./components/ModelFreshnessNotice";
import { ShapBars } from "./components/ShapBars";
import type { PredictedDirection } from "./types";

interface ForecastCardProps {
  ticker: string;
}

const DIRECTION_TONE: Record<PredictedDirection, string> = {
  Bullish: "text-bullish bg-bullish/10 border-bullish/30",
  Bearish: "text-bearish bg-bearish/10 border-bearish/30",
  Neutral: "text-muted bg-border/30 border-border",
};

// Data-sufficiency / model-availability responses are legitimate, expected
// states (see docs/ml-pipeline.md "Inference serving") — shown as an
// honest EmptyState, never as an alarming ErrorState.
const KNOWN_UNAVAILABLE_MESSAGES: Record<string, string> = {
  INSUFFICIENT_HISTORY: "Not enough price history yet to generate a forecast for this stock.",
  UNSUPPORTED_TICKER: "This stock isn't covered by the current research model.",
  MODEL_UNAVAILABLE: "No trained forecasting model is available right now.",
  DATA_VALIDATION_FAILED: "This stock's price history failed data validation.",
};

export function ForecastCard({ ticker }: ForecastCardProps) {
  const [showExplanation, setShowExplanation] = useState(false);

  const forecastQuery = useQuery({
    queryKey: ["forecast", ticker],
    queryFn: () => getForecast(ticker),
    retry: false,
  });

  const explanationQuery = useQuery({
    queryKey: ["forecast", "explanation", ticker],
    queryFn: () => getForecastExplanation(ticker, 5),
    enabled: showExplanation && forecastQuery.isSuccess,
    retry: false,
  });

  if (forecastQuery.isLoading) {
    return (
      <Card className="p-4">
        <Skeleton className="h-40 w-full" />
      </Card>
    );
  }

  if (forecastQuery.isError) {
    const error = forecastQuery.error;
    const knownMessage =
      error instanceof ApiError ? KNOWN_UNAVAILABLE_MESSAGES[error.code] : undefined;
    if (knownMessage) {
      return (
        <Card className="p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">AI Forecast</p>
          <EmptyState title="Forecast unavailable" description={knownMessage} />
        </Card>
      );
    }
    return (
      <Card className="p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted">AI Forecast</p>
        <ErrorState onRetry={() => forecastQuery.refetch()} />
      </Card>
    );
  }

  const forecast = forecastQuery.data;
  if (!forecast) return null;

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted">AI Forecast</p>
        <span
          className={clsx(
            "rounded border px-2 py-0.5 text-xs font-semibold",
            DIRECTION_TONE[forecast.predicted_direction],
          )}
        >
          {forecast.predicted_direction}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <p className="text-xs text-muted">Expected {forecast.horizon_days}-day return</p>
          <p className="text-lg font-semibold">
            {forecast.expected_return !== null ? formatPercent(forecast.expected_return * 100) : "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Model</p>
          <p className="text-sm font-medium">XGBoost</p>
        </div>
        <div>
          <p className="text-xs text-muted">Horizon</p>
          <p className="text-sm font-medium">{forecast.horizon_days} trading days</p>
        </div>
        <div>
          <p className="text-xs text-muted">Data</p>
          <p className="text-sm font-medium capitalize">{forecast.data_source} dataset</p>
        </div>
      </div>

      {forecast.probabilities && (
        <div className="flex gap-3 text-xs text-muted">
          {(Object.entries(forecast.probabilities) as [PredictedDirection, number][]).map(
            ([direction, probability]) => (
              <span key={direction}>
                {direction} {(probability * 100).toFixed(0)}%
              </span>
            ),
          )}
        </div>
      )}

      {forecast.training_period_start && forecast.training_period_end && (
        <ModelFreshnessNotice
          trainingStart={forecast.training_period_start}
          trainingEnd={forecast.training_period_end}
          evaluationEnd={forecast.evaluation_period_end}
        />
      )}

      <p className="text-xs text-muted">{forecast.disclaimer}</p>

      <div>
        <button
          type="button"
          onClick={() => setShowExplanation((v) => !v)}
          className="text-xs font-medium text-primary hover:underline"
        >
          {showExplanation ? "Hide explanation" : "Why this prediction?"}
        </button>

        {showExplanation && (
          <div className="mt-3 border-t border-border pt-3">
            {explanationQuery.isLoading && <Skeleton className="h-24 w-full" />}
            {explanationQuery.isError && (
              <p className="text-xs text-muted">Explanation unavailable right now.</p>
            )}
            {explanationQuery.isSuccess && (
              <div className="flex flex-col gap-4">
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                    Why "{explanationQuery.data.predicted_direction}"
                  </p>
                  <ShapBars factors={explanationQuery.data.top_direction_factors} />
                </div>
                {explanationQuery.data.top_return_factors.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                      Return-magnitude factors
                    </p>
                    <ShapBars factors={explanationQuery.data.top_return_factors} />
                  </div>
                )}
                <p className="text-xs text-muted">{explanationQuery.data.methodology_note}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
