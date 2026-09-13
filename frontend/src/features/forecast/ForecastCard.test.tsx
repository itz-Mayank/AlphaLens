import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";

import * as forecastApi from "./api";
import { ForecastCard } from "./ForecastCard";
import type { ForecastExplanationResponse, ForecastResponse } from "./types";

vi.mock("./api");

function makeForecast(overrides: Partial<ForecastResponse> = {}): ForecastResponse {
  return {
    ticker: "AAPL",
    model_name: "xgboost",
    return_model_version: "xgboost_return-v1",
    direction_model_version: "xgboost_direction-v1",
    feature_version: "fs_v1",
    dataset_version: "research_sample_sp500_v1",
    horizon_days: 5,
    predicted_direction: "Bullish",
    expected_return: 0.018,
    probabilities: { Bearish: 0.14, Neutral: 0.23, Bullish: 0.63 },
    prediction_timestamp: "2026-09-11T00:00:00Z",
    data_timestamp: "2026-09-10",
    data_source: "demo",
    training_period_start: "2013-02-08",
    training_period_end: "2016-06-30",
    evaluation_period_end: "2018-02-07",
    disclaimer: "Research model output — not financial advice.",
    ...overrides,
  };
}

function makeExplanation(
  overrides: Partial<ForecastExplanationResponse> = {},
): ForecastExplanationResponse {
  return {
    ticker: "AAPL",
    predicted_direction: "Bullish",
    model_version: "xgboost_direction-v1",
    feature_version: "fs_v1",
    as_of: "2026-09-10",
    top_direction_factors: [
      { feature: "rsi_14", value: 63.2, contribution: 0.31, direction: "positive" },
      { feature: "momentum_10d", value: 1.2, contribution: -0.08, direction: "negative" },
    ],
    top_return_factors: [],
    data_source: "demo",
    methodology_note: "SHAP explains the contribution of features; it does not establish causality.",
    ...overrides,
  };
}

function renderCard(ticker = "AAPL") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ForecastCard ticker={ticker} />
    </QueryClientProvider>,
  );
}

describe("ForecastCard", () => {
  beforeEach(() => {
    vi.mocked(forecastApi.getForecast).mockReset();
    vi.mocked(forecastApi.getForecastExplanation).mockReset();
  });

  it("renders the predicted direction, expected return, and probabilities", async () => {
    vi.mocked(forecastApi.getForecast).mockResolvedValue(makeForecast());

    renderCard();

    expect(await screen.findByText("Bullish")).toBeInTheDocument();
    expect(screen.getByText("+1.80%")).toBeInTheDocument();
    expect(screen.getByText(/not financial advice/i)).toBeInTheDocument();
    expect(screen.getByText(/bullish 63%/i)).toBeInTheDocument();
  });

  it("flags the model as stale when its training data predates the staleness threshold", async () => {
    vi.mocked(forecastApi.getForecast).mockResolvedValue(
      makeForecast({ training_period_start: "2013-02-08", training_period_end: "2016-06-30" }),
    );

    renderCard();

    expect(await screen.findByText(/trained on data/i)).toBeInTheDocument();
    expect(screen.getByText(/not been validated against current market conditions/i)).toBeInTheDocument();
  });

  it("shows no staleness warning when training data is recent", async () => {
    const recent = new Date();
    recent.setMonth(recent.getMonth() - 1);
    vi.mocked(forecastApi.getForecast).mockResolvedValue(
      makeForecast({
        training_period_start: "2024-01-01",
        training_period_end: recent.toISOString().slice(0, 10),
      }),
    );

    renderCard();

    expect(await screen.findByText(/trained on data/i)).toBeInTheDocument();
    expect(screen.queryByText(/not been validated against current market conditions/i)).not.toBeInTheDocument();
  });

  it("shows an honest unavailable state for insufficient history, not an alarming error", async () => {
    vi.mocked(forecastApi.getForecast).mockRejectedValue(
      new ApiError(422, "INSUFFICIENT_HISTORY", "not enough history"),
    );

    renderCard();

    expect(await screen.findByText("Forecast unavailable")).toBeInTheDocument();
    expect(screen.getByText(/not enough price history/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("shows an honest unavailable state for an unsupported ticker", async () => {
    vi.mocked(forecastApi.getForecast).mockRejectedValue(
      new ApiError(422, "UNSUPPORTED_TICKER", "not covered"),
    );

    renderCard();

    expect(await screen.findByText(/isn't covered by the current research model/i)).toBeInTheDocument();
  });

  it("shows an honest unavailable state when no model is registered", async () => {
    vi.mocked(forecastApi.getForecast).mockRejectedValue(
      new ApiError(503, "MODEL_UNAVAILABLE", "no model"),
    );

    renderCard();

    expect(await screen.findByText(/no trained forecasting model/i)).toBeInTheDocument();
  });

  it("shows a retryable error state for an unexpected failure", async () => {
    vi.mocked(forecastApi.getForecast).mockRejectedValue(new Error("boom"));

    renderCard();

    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("loads and displays the explanation only after the user asks for it", async () => {
    vi.mocked(forecastApi.getForecast).mockResolvedValue(makeForecast());
    vi.mocked(forecastApi.getForecastExplanation).mockResolvedValue(makeExplanation());

    renderCard();
    await screen.findByText("Bullish");

    expect(forecastApi.getForecastExplanation).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /why this prediction/i }));

    expect(await screen.findByText("rsi_14")).toBeInTheDocument();
    expect(screen.getByText("+0.310")).toBeInTheDocument();
    expect(screen.getByText(/does not establish causality/i)).toBeInTheDocument();
  });
});
