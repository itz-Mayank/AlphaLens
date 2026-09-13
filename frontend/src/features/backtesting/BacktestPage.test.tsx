import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";

import * as backtestApi from "./api";
import { BacktestPage } from "./BacktestPage";
import type { BacktestResponse } from "./types";

vi.mock("./api");
vi.mock("./components/EquityCurveChart", () => ({
  EquityCurveChart: () => <div data-testid="equity-curve-chart-stub" />,
}));
vi.mock("./components/DrawdownChart", () => ({
  DrawdownChart: () => <div data-testid="drawdown-chart-stub" />,
}));

function makeResponse(overrides: Partial<BacktestResponse> = {}): BacktestResponse {
  return {
    tickers: ["AAPL", "MSFT"],
    start_date: "2024-01-01",
    end_date: "2024-06-01",
    model_name: "xgboost_direction",
    model_version: "xgboost_direction-v1",
    feature_version: "fs_v1",
    dataset_version: "research_sample_sp500_v1",
    commission_bps: 5,
    slippage_bps: 5,
    initial_capital: 100_000,
    equity_curve: [
      { ts: "2024-01-02", equity: 100_500, benchmark_equity: 100_200 },
      { ts: "2024-01-03", equity: 101_200, benchmark_equity: 100_800 },
    ],
    metrics: {
      cumulative_return: 0.05,
      cagr: 0.12,
      annualized_volatility: 0.15,
      sharpe_ratio: 1.2,
      sortino_ratio: 1.8,
      max_drawdown: -0.08,
      win_rate: 0.6,
      turnover_mean: 0.1,
      total_transaction_costs: 0.002,
      num_rebalance_days: 4,
      benchmark_cumulative_return: 0.03,
    },
    num_rebalance_events: 6,
    data_sources: ["demo"],
    disclaimer: "Research backtest — not a live trading result and not financial advice.",
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BacktestPage />
    </QueryClientProvider>,
  );
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText(/start date/i), { target: { value: "2024-01-01" } });
  fireEvent.change(screen.getByLabelText(/end date/i), { target: { value: "2024-06-01" } });
  fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
}

describe("BacktestPage", () => {
  beforeEach(() => {
    vi.mocked(backtestApi.runBacktest).mockReset();
  });

  it("runs a backtest and renders real metrics from the response", async () => {
    vi.mocked(backtestApi.runBacktest).mockResolvedValue(makeResponse());

    renderPage();
    fillAndSubmit();

    expect(await screen.findByText("5.00%")).toBeInTheDocument(); // cumulative return
    expect(screen.getByText("1.20")).toBeInTheDocument(); // sharpe ratio
    expect(screen.getByText("-8.00%")).toBeInTheDocument(); // max drawdown
    expect(screen.getAllByText(/not a live trading result/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId("equity-curve-chart-stub")).toBeInTheDocument();

    expect(backtestApi.runBacktest).toHaveBeenCalledWith(
      expect.objectContaining({ tickers: ["AAPL", "MSFT", "JPM"] }),
    );

    // Execution assumptions echo the response's own real values, not the form's live state.
    expect(screen.getAllByText("5 bps").length).toBe(2);
    expect(screen.getByText("$100,000")).toBeInTheDocument();
    expect(screen.getByText(/executed with the configured lag/i)).toBeInTheDocument();
    expect(screen.getByTestId("drawdown-chart-stub")).toBeInTheDocument();
  });

  it("shows a readable message for a known error code", async () => {
    vi.mocked(backtestApi.runBacktest).mockRejectedValue(
      new ApiError(422, "INSUFFICIENT_HISTORY", "not enough history"),
    );

    renderPage();
    fillAndSubmit();

    expect(
      await screen.findByText(/not enough price history for the requested/i),
    ).toBeInTheDocument();
  });

  it("disables the run button until both dates are set", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /run backtest/i })).toBeDisabled();
  });
});
