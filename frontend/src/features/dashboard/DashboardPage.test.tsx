import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/authStore";
import * as forecastApi from "@/features/forecast/api";
import type { ForecastResponse } from "@/features/forecast/types";

import * as dashboardApi from "./api";
import { DashboardPage } from "./DashboardPage";
import type { DashboardOverview } from "./types";

vi.mock("./api");
vi.mock("@/features/forecast/api");

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

const sampleUser = {
  id: "1",
  email: "jane@example.com",
  full_name: "Jane Doe",
  role: "USER" as const,
  is_active: true,
  is_email_verified: false,
  created_at: "2024-01-01T00:00:00Z",
};

function emptyOverview(): DashboardOverview {
  return {
    market_summary: {
      total_securities: 0,
      securities_with_price_data: 0,
      latest_market_data_ts: null,
      data_sources: [],
      freshness_status: "no_data",
    },
    market_movers: { as_of: null, top_gainers: [], top_losers: [], most_active: [] },
    sector_overview: { as_of: null, sectors: [] },
    market_breadth: {
      as_of: null,
      status: "unavailable",
      advancing: null,
      declining: null,
      unchanged: null,
      no_data: 0,
    },
    recent_activity: [],
  };
}

function populatedOverview(): DashboardOverview {
  return {
    market_summary: {
      total_securities: 2,
      securities_with_price_data: 2,
      latest_market_data_ts: "2024-01-10T00:00:00Z",
      data_sources: ["demo"],
      freshness_status: "current",
    },
    market_movers: {
      as_of: "2024-01-10T00:00:00Z",
      top_gainers: [
        {
          ticker: "AAPL",
          name: "Apple Inc.",
          sector: "Technology",
          last_price: "150.00",
          change_percent: "5.00",
          volume: 1000,
        },
      ],
      top_losers: [
        {
          ticker: "XOM",
          name: "Exxon",
          sector: "Energy",
          last_price: "90.00",
          change_percent: "-3.00",
          volume: 500,
        },
      ],
      most_active: [
        { ticker: "AAPL", name: "Apple Inc.", sector: "Technology", last_price: "150.00", volume: 1000 },
      ],
    },
    sector_overview: {
      as_of: "2024-01-10T00:00:00Z",
      sectors: [
        { sector: "Technology", security_count: 1, securities_with_data: 1, average_return_percent: "5.00" },
        { sector: "Energy", security_count: 1, securities_with_data: 1, average_return_percent: "-3.00" },
      ],
    },
    market_breadth: {
      as_of: "2024-01-10T00:00:00Z",
      status: "ok",
      advancing: 1,
      declining: 1,
      unchanged: 0,
      no_data: 0,
    },
    recent_activity: [
      { ticker: "AAPL", name: "Apple Inc.", last_price: "150.00", as_of: "2024-01-10T00:00:00Z" },
    ],
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/app"]}>
        <Routes>
          <Route path="/app" element={<DashboardPage />} />
          <Route path="/app/stocks/:ticker" element={<div>Detail placeholder</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.mocked(dashboardApi.getDashboardOverview).mockReset();
    vi.mocked(forecastApi.getForecast).mockReset();
    vi.mocked(forecastApi.getForecast).mockImplementation((ticker) =>
      Promise.resolve(makeForecast({ ticker })),
    );
    useAuthStore.setState({ user: sampleUser, accessToken: "token", status: "authenticated" });
  });

  it("shows an honest empty state before any data has been ingested", async () => {
    vi.mocked(dashboardApi.getDashboardOverview).mockResolvedValue(emptyOverview());

    renderPage();

    expect(await screen.findByText(/no market movers yet/i)).toBeInTheDocument();
    expect(screen.getByText(/market breadth unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/no sectors tracked yet/i)).toBeInTheDocument();
    expect(screen.getByText(/no recently updated securities/i)).toBeInTheDocument();
    expect(screen.getByText(/no ai signals available/i)).toBeInTheDocument();
    expect(forecastApi.getForecast).not.toHaveBeenCalled();
    expect(screen.queryByText(/demo data/i)).not.toBeInTheDocument();
  });

  it("renders real data across every section, with the demo banner", async () => {
    vi.mocked(dashboardApi.getDashboardOverview).mockResolvedValue(populatedOverview());

    renderPage();

    expect((await screen.findAllByText(/demo data/i)).length).toBeGreaterThan(0);
    expect(screen.getByText("Top Gainers")).toBeInTheDocument();
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getByText("XOM")).toBeInTheDocument();
    expect(screen.getAllByText("+5.00%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-3.00%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Technology").length).toBeGreaterThan(0);
    expect(screen.getByText(/advancing/i)).toBeInTheDocument();

    expect(await screen.findByText("AI Signals")).toBeInTheDocument();
    expect(forecastApi.getForecast).toHaveBeenCalledWith("AAPL");
    expect(forecastApi.getForecast).toHaveBeenCalledWith("XOM");
    expect(screen.getAllByText("Bullish").length).toBeGreaterThan(0);
  });

  it("navigates to the stock detail page when a mover is clicked", async () => {
    vi.mocked(dashboardApi.getDashboardOverview).mockResolvedValue(populatedOverview());
    const user = userEvent.setup();

    renderPage();

    const gainerButtons = await screen.findAllByRole("button", { name: /AAPL/i });
    await user.click(gainerButtons[0]);

    expect(await screen.findByText("Detail placeholder")).toBeInTheDocument();
  });

  it("shows an error state with a working retry button", async () => {
    vi.mocked(dashboardApi.getDashboardOverview).mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();

    renderPage();

    await screen.findByRole("button", { name: /retry/i });
    vi.mocked(dashboardApi.getDashboardOverview).mockResolvedValue(emptyOverview());

    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    });
  });
});
