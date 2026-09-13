import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as forecastApi from "@/features/forecast/api";
import type { ForecastExplanationResponse, ForecastResponse } from "@/features/forecast/types";
import * as newsApi from "@/features/news/api";
import * as watchlistApi from "@/features/watchlist/api";
import { ApiError } from "@/lib/api-client";

import * as stocksApi from "./api";
import { StockDetailPage } from "./StockDetailPage";
import type { StockDetail } from "./types";

vi.mock("./api");
vi.mock("@/features/forecast/api");
vi.mock("@/features/news/api");
vi.mock("@/features/watchlist/api");

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
    top_direction_factors: [{ feature: "rsi_14", value: 63.2, contribution: 0.31, direction: "positive" }],
    top_return_factors: [],
    data_source: "demo",
    methodology_note: "SHAP explains contribution; not causality.",
    ...overrides,
  };
}

function makeDetail(overrides: Partial<StockDetail> = {}): StockDetail {
  return {
    id: 1,
    ticker: "AAPL",
    name: "Apple Inc.",
    exchange: "NASDAQ",
    sector: "Technology",
    industry: "Consumer Electronics",
    currency: "USD",
    status: "ACTIVE",
    data_source: "demo",
    last_price: "150.00",
    change: "2.50",
    change_percent: "1.69",
    volume: 32_500_000,
    as_of: "2024-01-05T00:00:00Z",
    week_52_high: "199.00",
    week_52_low: "120.00",
    ...overrides,
  };
}

function renderAt(ticker: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/app/stocks/${ticker}`]}>
        <Routes>
          <Route path="/app/stocks" element={<div>Explorer placeholder</div>} />
          <Route path="/app/stocks/:ticker" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StockDetailPage", () => {
  beforeEach(() => {
    vi.mocked(stocksApi.getStockDetail).mockReset();
    vi.mocked(stocksApi.getStockPrices).mockReset();
    vi.mocked(forecastApi.getForecast).mockReset();
    vi.mocked(forecastApi.getForecastExplanation).mockReset();
    vi.mocked(newsApi.getStockNews).mockReset();
    vi.mocked(newsApi.getStockSentiment).mockReset();
    vi.mocked(watchlistApi.listWatchlists).mockReset();
  });

  it("renders quote and 52-week range once loaded", async () => {
    vi.mocked(stocksApi.getStockDetail).mockResolvedValue(makeDetail());
    vi.mocked(stocksApi.getStockPrices).mockResolvedValue({
      ticker: "AAPL",
      data_source: "demo",
      bars: [
        {
          ts: "2024-01-05T00:00:00Z",
          open: "148",
          high: "151",
          low: "147",
          close: "150",
          adjusted_close: "150",
          volume: 32_500_000,
        },
      ],
    });

    renderAt("AAPL");

    expect(await screen.findByRole("heading", { name: "AAPL" })).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("$150.00")).toBeInTheDocument();
    expect(screen.getByText("$199.00")).toBeInTheDocument();
    expect(screen.getByText("$120.00")).toBeInTheDocument();
    expect(screen.getAllByText(/demo data/i).length).toBeGreaterThan(0);
  });

  it("shows a not-found empty state for an un-ingested ticker", async () => {
    vi.mocked(stocksApi.getStockDetail).mockRejectedValue(
      new ApiError(404, "STOCK_NOT_FOUND", "No stock found."),
    );

    renderAt("ZZZZ");

    expect(await screen.findByText(/no data for "zzzz"/i)).toBeInTheDocument();
    expect(screen.getByText(/back to stock explorer/i)).toBeInTheDocument();
  });

  it("shows a generic error state for a non-404 failure, with retry", async () => {
    vi.mocked(stocksApi.getStockDetail).mockRejectedValue(new Error("boom"));

    renderAt("AAPL");

    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("switches to the AI Forecast tab and renders the forecast with SHAP factors", async () => {
    vi.mocked(stocksApi.getStockDetail).mockResolvedValue(makeDetail());
    vi.mocked(stocksApi.getStockPrices).mockResolvedValue({ ticker: "AAPL", data_source: "demo", bars: [] });
    vi.mocked(forecastApi.getForecast).mockResolvedValue(makeForecast());
    vi.mocked(forecastApi.getForecastExplanation).mockResolvedValue(makeExplanation());
    const user = userEvent.setup();

    renderAt("AAPL");
    await screen.findByRole("heading", { name: "AAPL" });

    await user.click(screen.getByRole("tab", { name: /ai forecast/i }));

    expect(await screen.findByText("Bullish")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /why this prediction/i }));
    expect(await screen.findByText("rsi_14")).toBeInTheDocument();
  });

  it("switches to the Technicals tab and renders indicator values", async () => {
    vi.mocked(stocksApi.getStockDetail).mockResolvedValue(makeDetail());
    vi.mocked(stocksApi.getStockPrices).mockResolvedValue({ ticker: "AAPL", data_source: "demo", bars: [] });
    vi.mocked(forecastApi.getForecastExplanation).mockResolvedValue(
      makeExplanation({
        top_direction_factors: [
          { feature: "rsi_14", value: 61.4, contribution: 0.12, direction: "positive" },
        ],
      }),
    );
    const user = userEvent.setup();

    renderAt("AAPL");
    await screen.findByRole("heading", { name: "AAPL" });

    await user.click(screen.getByRole("tab", { name: /technicals/i }));

    expect(await screen.findByText("RSI (14)")).toBeInTheDocument();
    expect(screen.getByText("61.4")).toBeInTheDocument();
    expect(forecastApi.getForecastExplanation).toHaveBeenCalledWith("AAPL", 27);
  });

  it("switches to the News & Sentiment tab and shows the honest no-data state", async () => {
    vi.mocked(stocksApi.getStockDetail).mockResolvedValue(makeDetail());
    vi.mocked(stocksApi.getStockPrices).mockResolvedValue({ ticker: "AAPL", data_source: "demo", bars: [] });
    vi.mocked(newsApi.getStockNews).mockResolvedValue({ ticker: "AAPL", articles: [], data_sources: [] });
    vi.mocked(newsApi.getStockSentiment).mockResolvedValue({
      ticker: "AAPL",
      last_24h: {
        as_of: "2026-09-10T00:00:00Z",
        window_days: 1,
        since: "2026-09-09T00:00:00Z",
        until: "2026-09-10T00:00:00Z",
        article_count: 0,
        positive_count: 0,
        neutral_count: 0,
        negative_count: 0,
        average_sentiment_score: null,
        sentiment_momentum: null,
      },
      last_7d: {
        as_of: "2026-09-10T00:00:00Z",
        window_days: 7,
        since: "2026-09-03T00:00:00Z",
        until: "2026-09-10T00:00:00Z",
        article_count: 0,
        positive_count: 0,
        neutral_count: 0,
        negative_count: 0,
        average_sentiment_score: null,
        sentiment_momentum: null,
      },
      model_version: "finbert-v1",
      disclaimer: "Not financial advice.",
    });
    const user = userEvent.setup();

    renderAt("AAPL");
    await screen.findByRole("heading", { name: "AAPL" });

    await user.click(screen.getByRole("tab", { name: /news & sentiment/i }));

    expect(await screen.findByText(/no sentiment data yet/i)).toBeInTheDocument();
    expect(screen.getByText(/no recent news/i)).toBeInTheDocument();
  });

  it("quick-adds the ticker to a watchlist from the header", async () => {
    vi.mocked(stocksApi.getStockDetail).mockResolvedValue(makeDetail());
    vi.mocked(stocksApi.getStockPrices).mockResolvedValue({ ticker: "AAPL", data_source: "demo", bars: [] });
    vi.mocked(watchlistApi.listWatchlists).mockResolvedValue([
      { id: "w1", name: "Tech Watch", description: null, created_at: "2026-01-01", updated_at: "2026-01-01", item_count: 2 },
    ]);
    vi.mocked(watchlistApi.addWatchlistItem).mockResolvedValue({
      id: "w1",
      name: "Tech Watch",
      description: null,
      created_at: "2026-01-01",
      updated_at: "2026-01-01",
      items: [],
    });
    const user = userEvent.setup();

    renderAt("AAPL");
    await screen.findByRole("heading", { name: "AAPL" });

    await user.click(screen.getByRole("button", { name: /\+ watchlist/i }));
    await user.click(await screen.findByText("Tech Watch"));

    expect(watchlistApi.addWatchlistItem).toHaveBeenCalledWith("w1", "AAPL");
    expect(await screen.findByText("Added.")).toBeInTheDocument();
  });
});
