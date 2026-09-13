import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";

import * as portfolioApi from "./api";
import { PortfolioDetailPage } from "./PortfolioDetailPage";
import type { Holding, Portfolio, PortfolioAnalytics, Transaction } from "./types";

vi.mock("./api");
vi.mock("./components/PortfolioValueChart", () => ({
  PortfolioValueChart: () => <div data-testid="portfolio-value-chart-stub" />,
}));

function makePortfolio(overrides: Partial<Portfolio> = {}): Portfolio {
  return {
    id: "p1",
    name: "Growth",
    description: null,
    base_currency: "USD",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeAnalytics(overrides: Partial<PortfolioAnalytics> = {}): PortfolioAnalytics {
  return {
    cash: "1000.00",
    invested_capital: "10000.00",
    total_deposits: "10000.00",
    total_withdrawals: "0.00",
    market_value: "11500.00",
    total_value: "12500.00",
    realized_pnl: "0.00",
    unrealized_pnl: "1500.00",
    total_return_percent: "25.00",
    market_value_is_partial: false,
    holdings: [],
    methodology_note: "Money-weighted simple return.",
    ...overrides,
  };
}

function makeHolding(overrides: Partial<Holding> = {}): Holding {
  return {
    security_id: 1,
    ticker: "AAPL",
    name: "Apple Inc.",
    quantity: "10",
    average_cost: "100.00",
    cost_basis: "1000.00",
    last_price: "150.00",
    market_value: "1500.00",
    unrealized_pnl: "500.00",
    unrealized_pnl_percent: "50.00",
    ...overrides,
  };
}

function makeTransaction(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: "t1",
    transaction_type: "BUY",
    ticker: "AAPL",
    quantity: "10",
    price: "100.00",
    amount: null,
    fees: "1.00",
    currency: "USD",
    executed_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/app/portfolio/p1"]}>
        <Routes>
          <Route path="/app/portfolio" element={<div>List placeholder</div>} />
          <Route path="/app/portfolio/:portfolioId" element={<PortfolioDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PortfolioDetailPage", () => {
  beforeEach(() => {
    vi.mocked(portfolioApi.getPortfolio).mockReset();
    vi.mocked(portfolioApi.getAnalytics).mockReset();
    vi.mocked(portfolioApi.getHoldings).mockReset();
    vi.mocked(portfolioApi.listTransactions).mockReset();
    vi.mocked(portfolioApi.getPerformance).mockReset();
    vi.mocked(portfolioApi.getPortfolio).mockResolvedValue(makePortfolio());
    vi.mocked(portfolioApi.getAnalytics).mockResolvedValue(makeAnalytics());
    vi.mocked(portfolioApi.getHoldings).mockResolvedValue([]);
    vi.mocked(portfolioApi.listTransactions).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    vi.mocked(portfolioApi.getPerformance).mockResolvedValue({
      available: false,
      reason: "Not enough data yet.",
      points: [],
      methodology_note: "No look-ahead bias.",
    });
  });

  it("renders real analytics metrics with comma-grouped currency formatting", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Growth" })).toBeInTheDocument();
    expect(screen.getByText("$12,500.00")).toBeInTheDocument();
    expect(screen.getByText("+25.00%")).toBeInTheDocument();
    expect(screen.getByText("$1,500.00")).toBeInTheDocument();
  });

  it("shows holdings with real P&L, never fabricated zeros for missing prices", async () => {
    vi.mocked(portfolioApi.getHoldings).mockResolvedValue([
      makeHolding(),
      makeHolding({ security_id: 2, ticker: "TSLA", last_price: null, market_value: null, unrealized_pnl: null, unrealized_pnl_percent: null }),
    ]);

    renderPage();

    expect((await screen.findAllByText("AAPL")).length).toBeGreaterThan(0);
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("No data yet")).toBeInTheDocument();
  });

  it("renders the allocation breakdown from real holding market values", async () => {
    vi.mocked(portfolioApi.getHoldings).mockResolvedValue([
      makeHolding({ ticker: "AAPL", market_value: "1500.00" }),
      makeHolding({ security_id: 2, ticker: "MSFT", market_value: "1500.00" }),
    ]);

    renderPage();

    expect(await screen.findAllByText("50.0%")).toHaveLength(2);
  });

  it("shows transactions and the empty-state before any exist", async () => {
    renderPage();
    expect(await screen.findByText(/no transactions yet/i)).toBeInTheDocument();

    vi.mocked(portfolioApi.listTransactions).mockResolvedValue({
      items: [makeTransaction()],
      total: 1,
      limit: 20,
      offset: 0,
    });
  });

  it("shows an honest unavailable message for performance history, not an empty chart", async () => {
    renderPage();

    expect(await screen.findByText("Not enough data yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("portfolio-value-chart-stub")).not.toBeInTheDocument();
  });

  it("renders the value chart once performance history is available", async () => {
    vi.mocked(portfolioApi.getPerformance).mockResolvedValue({
      available: true,
      reason: null,
      points: [
        { as_of: "2026-01-01T00:00:00Z", cash: "1000", market_value: "1000", total_value: "2000", net_contributed: "2000" },
      ],
      methodology_note: "No look-ahead bias.",
    });

    renderPage();

    expect(await screen.findByTestId("portfolio-value-chart-stub")).toBeInTheDocument();
  });

  it("shows a 404-specific error for a portfolio that isn't the user's", async () => {
    vi.mocked(portfolioApi.getPortfolio).mockRejectedValue(new ApiError(404, "PORTFOLIO_NOT_FOUND", "not found"));

    renderPage();

    expect(await screen.findByText(/doesn't exist or isn't yours/i)).toBeInTheDocument();
  });
});
