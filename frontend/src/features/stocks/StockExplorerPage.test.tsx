import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as stocksApi from "./api";
import { StockExplorerPage } from "./StockExplorerPage";
import type { Page, StockListItem } from "./types";

vi.mock("./api");

function makeStock(overrides: Partial<StockListItem> = {}): StockListItem {
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
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/app/stocks"]}>
        <Routes>
          <Route path="/app/stocks" element={<StockExplorerPage />} />
          <Route path="/app/stocks/:ticker" element={<div>Detail placeholder</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StockExplorerPage", () => {
  beforeEach(() => {
    vi.mocked(stocksApi.listStocks).mockReset();
  });

  it("shows an empty state when there are no stocks", async () => {
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    } satisfies Page<StockListItem>);

    renderPage();

    expect(await screen.findByText(/no stocks yet/i)).toBeInTheDocument();
  });

  it("renders stocks with formatted price, change, and volume", async () => {
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [makeStock()],
      total: 1,
      limit: 20,
      offset: 0,
    } satisfies Page<StockListItem>);

    renderPage();

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("$150.00")).toBeInTheDocument();
    expect(screen.getByText("+1.69%")).toBeInTheDocument();
    expect(screen.getByText("32.5M")).toBeInTheDocument();
    expect(screen.getByText(/demo data/i)).toBeInTheDocument();
  });

  it("navigates to the stock detail page when a row is clicked", async () => {
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [makeStock()],
      total: 1,
      limit: 20,
      offset: 0,
    } satisfies Page<StockListItem>);
    const user = userEvent.setup();

    renderPage();

    await user.click(await screen.findByText("AAPL"));

    expect(await screen.findByText("Detail placeholder")).toBeInTheDocument();
  });

  it("debounces search input before querying", async () => {
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    } satisfies Page<StockListItem>);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/no stocks yet/i);
    vi.mocked(stocksApi.listStocks).mockClear();

    await user.type(screen.getByLabelText(/search ticker/i), "AAPL");

    await waitFor(
      () => {
        const searchCalls = vi
          .mocked(stocksApi.listStocks)
          .mock.calls.filter(([params]) => params.q === "AAPL");
        expect(searchCalls.length).toBeGreaterThan(0);
      },
      { timeout: 2000 },
    );
  });

  it("shows an error state with a working retry button", async () => {
    vi.mocked(stocksApi.listStocks).mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();

    renderPage();

    await screen.findByRole("button", { name: /retry/i });
    vi.mocked(stocksApi.listStocks).mockClear();
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [makeStock()],
      total: 1,
      limit: 20,
      offset: 0,
    } satisfies Page<StockListItem>);

    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
  });
});
