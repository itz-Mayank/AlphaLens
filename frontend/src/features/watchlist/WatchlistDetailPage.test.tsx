import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as forecastApi from "@/features/forecast/api";
import type { ForecastResponse } from "@/features/forecast/types";
import { ApiError } from "@/lib/api-client";

import * as watchlistApi from "./api";
import type { WatchlistDetail, WatchlistItem } from "./types";
import { WatchlistDetailPage } from "./WatchlistDetailPage";

vi.mock("./api");
vi.mock("@/features/forecast/api");

function makeItem(overrides: Partial<WatchlistItem> = {}): WatchlistItem {
  return {
    security_id: 1,
    ticker: "AAPL",
    name: "Apple Inc.",
    sector: "Technology",
    last_price: "150.00",
    change: "2.50",
    change_percent: "1.69",
    volume: 1_000_000,
    as_of: "2026-09-10T00:00:00Z",
    data_unavailable: false,
    ...overrides,
  };
}

function makeDetail(overrides: Partial<WatchlistDetail> = {}): WatchlistDetail {
  return {
    id: "w1",
    name: "Core Holdings",
    description: "My tracked names",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    items: [makeItem()],
    ...overrides,
  };
}

function makeForecast(overrides: Partial<ForecastResponse> = {}): ForecastResponse {
  return {
    ticker: "AAPL",
    model_name: "xgboost",
    return_model_version: "v1",
    direction_model_version: "v1",
    feature_version: "fs_v1",
    dataset_version: "research_sample_sp500_v1",
    horizon_days: 5,
    predicted_direction: "Bullish",
    expected_return: 0.01,
    probabilities: { Bearish: 0.2, Neutral: 0.2, Bullish: 0.6 },
    prediction_timestamp: "2026-09-11T00:00:00Z",
    data_timestamp: "2026-09-10",
    data_source: "demo",
    training_period_start: "2013-02-08",
    training_period_end: "2016-06-30",
    evaluation_period_end: "2018-02-07",
    disclaimer: "Research model output.",
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/app/watchlists/w1"]}>
        <Routes>
          <Route path="/app/watchlists" element={<div>List placeholder</div>} />
          <Route path="/app/watchlists/:watchlistId" element={<WatchlistDetailPage />} />
          <Route path="/app/stocks/:ticker" element={<div>Detail placeholder</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WatchlistDetailPage", () => {
  beforeEach(() => {
    vi.mocked(watchlistApi.getWatchlist).mockReset();
    vi.mocked(watchlistApi.addWatchlistItem).mockReset();
    vi.mocked(watchlistApi.removeWatchlistItem).mockReset();
    vi.mocked(forecastApi.getForecast).mockReset();
    vi.mocked(forecastApi.getForecast).mockImplementation((ticker) =>
      Promise.resolve(makeForecast({ ticker })),
    );
  });

  it("shows an empty state when the watchlist has no items", async () => {
    vi.mocked(watchlistApi.getWatchlist).mockResolvedValue(makeDetail({ items: [] }));

    renderPage();

    expect(await screen.findByText(/no stocks yet/i)).toBeInTheDocument();
  });

  it("renders real quote data and an AI signal for a small watchlist", async () => {
    vi.mocked(watchlistApi.getWatchlist).mockResolvedValue(makeDetail());

    renderPage();

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("$150.00")).toBeInTheDocument();
    expect(screen.getByText("+1.69%")).toBeInTheDocument();
    expect(await screen.findByText("Bullish")).toBeInTheDocument();
    expect(forecastApi.getForecast).toHaveBeenCalledWith("AAPL");
  });

  it("shows 'No data yet' rather than a fabricated price when a quote is unavailable", async () => {
    vi.mocked(watchlistApi.getWatchlist).mockResolvedValue(
      makeDetail({ items: [makeItem({ data_unavailable: true, last_price: null, change_percent: null })] }),
    );

    renderPage();

    expect(await screen.findByText("No data yet")).toBeInTheDocument();
  });

  it("omits the AI Signal column for a watchlist larger than the enrichment cap", async () => {
    const items = Array.from({ length: 16 }, (_, i) => makeItem({ security_id: i, ticker: `T${i}` }));
    vi.mocked(watchlistApi.getWatchlist).mockResolvedValue(makeDetail({ items }));

    renderPage();

    await screen.findByText("T0");
    expect(screen.queryByText("AI Signal")).not.toBeInTheDocument();
    expect(screen.getByText(/shown for watchlists of up to 15 stocks/i)).toBeInTheDocument();
    expect(forecastApi.getForecast).not.toHaveBeenCalled();
  });

  it("adds a ticker and shows a known error message on failure", async () => {
    vi.mocked(watchlistApi.getWatchlist).mockResolvedValue(makeDetail());
    vi.mocked(watchlistApi.addWatchlistItem).mockRejectedValue(
      new ApiError(404, "STOCK_NOT_FOUND", "unknown ticker"),
    );
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("AAPL");

    await user.type(screen.getByLabelText(/add ticker/i), "zzzz");
    await user.click(screen.getByRole("button", { name: /add to watchlist/i }));

    expect(watchlistApi.addWatchlistItem).toHaveBeenCalledWith("w1", "ZZZZ");
    expect(await screen.findByText(/isn't known to this deployment/i)).toBeInTheDocument();
  });

  it("removes an item from the watchlist", async () => {
    vi.mocked(watchlistApi.getWatchlist).mockResolvedValue(makeDetail());
    vi.mocked(watchlistApi.removeWatchlistItem).mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("AAPL");

    await user.click(screen.getByRole("button", { name: /remove/i }));

    expect(watchlistApi.removeWatchlistItem).toHaveBeenCalledWith("w1", "AAPL");
  });

  it("navigates to stock detail when a row is clicked", async () => {
    vi.mocked(watchlistApi.getWatchlist).mockResolvedValue(makeDetail());
    const user = userEvent.setup();

    renderPage();
    await user.click(await screen.findByText("AAPL"));

    expect(await screen.findByText("Detail placeholder")).toBeInTheDocument();
  });

  it("shows a 404-specific error for a watchlist that isn't the user's", async () => {
    vi.mocked(watchlistApi.getWatchlist).mockRejectedValue(
      new ApiError(404, "WATCHLIST_NOT_FOUND", "not found"),
    );

    renderPage();

    expect(await screen.findByText(/doesn't exist or isn't yours/i)).toBeInTheDocument();
  });
});
