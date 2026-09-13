import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as stocksApi from "@/features/stocks/api";
import type { Page, StockListItem } from "@/features/stocks/types";
import { useAuthStore } from "@/stores/authStore";

import { GlobalSearch } from "./GlobalSearch";

vi.mock("@/features/stocks/api");

const adminUser = {
  id: "1",
  email: "admin@example.com",
  full_name: "Admin",
  role: "ADMIN" as const,
  is_active: true,
  is_email_verified: true,
  created_at: "2026-01-01T00:00:00Z",
};

function renderSearch() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/app"]}>
        <Routes>
          <Route path="/app" element={<GlobalSearch />} />
          <Route path="/app/stocks/:ticker" element={<div>Detail placeholder</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("GlobalSearch", () => {
  beforeEach(() => {
    vi.mocked(stocksApi.listStocks).mockReset();
    vi.mocked(stocksApi.discoverSecurities).mockReset();
    vi.mocked(stocksApi.ingestTicker).mockReset();
    useAuthStore.setState({ user: adminUser, accessToken: "t", status: "authenticated" });
  });

  it("shows real tracked matches from the local catalog", async () => {
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [
        {
          id: 1,
          ticker: "AAPL",
          name: "Apple Inc.",
          exchange: "NASDAQ",
          sector: "Technology",
          industry: null,
          currency: "USD",
          status: "ACTIVE",
          data_source: "demo",
          last_price: "150.00",
          change: "1.00",
          change_percent: "0.67",
          volume: 1000,
          as_of: "2026-09-10T00:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
    } satisfies Page<StockListItem>);
    vi.mocked(stocksApi.discoverSecurities).mockResolvedValue([]);
    const user = userEvent.setup();

    renderSearch();
    await user.type(screen.getByRole("combobox"), "AAPL");

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("$150.00")).toBeInTheDocument();
  });

  it("surfaces a never-tracked ticker via live discovery, with an Add & Research action for an admin", async () => {
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [],
      total: 0,
      limit: 8,
      offset: 0,
    } satisfies Page<StockListItem>);
    vi.mocked(stocksApi.discoverSecurities).mockResolvedValue([
      { ticker: "AMD", name: "Advanced Micro Devices, Inc.", exchange: "NASDAQ", currency: "USD", already_tracked: false },
    ]);
    vi.mocked(stocksApi.ingestTicker).mockResolvedValue({ job_id: "job-1", status: "COMPLETED" });
    const user = userEvent.setup();

    renderSearch();
    await user.type(screen.getByRole("combobox"), "AMD");

    expect(await screen.findByText("AMD")).toBeInTheDocument();
    expect(screen.getByText(/not yet tracked/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /add & research/i }));

    expect(stocksApi.ingestTicker).toHaveBeenCalledWith("AMD");
    expect(await screen.findByText("Detail placeholder")).toBeInTheDocument();
  });

  it("shows an honest 'ask an analyst' message for a plain user, never an ingest button", async () => {
    useAuthStore.setState({
      user: { ...adminUser, role: "USER" },
      accessToken: "t",
      status: "authenticated",
    });
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [],
      total: 0,
      limit: 8,
      offset: 0,
    } satisfies Page<StockListItem>);
    vi.mocked(stocksApi.discoverSecurities).mockResolvedValue([
      { ticker: "AMD", name: "Advanced Micro Devices, Inc.", exchange: "NASDAQ", currency: "USD", already_tracked: false },
    ]);
    const user = userEvent.setup();

    renderSearch();
    await user.type(screen.getByRole("combobox"), "AMD");

    expect(await screen.findByText(/ask an analyst to add/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add & research/i })).not.toBeInTheDocument();
  });

  it("does not surface a discovery result already flagged as tracked", async () => {
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [],
      total: 0,
      limit: 8,
      offset: 0,
    } satisfies Page<StockListItem>);
    vi.mocked(stocksApi.discoverSecurities).mockResolvedValue([
      { ticker: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", currency: "USD", already_tracked: true },
    ]);
    const user = userEvent.setup();

    renderSearch();
    await user.type(screen.getByRole("combobox"), "AAPL");

    expect(await screen.findByText(/no securities match/i)).toBeInTheDocument();
  });

  it("shows an honest message when live discovery is unavailable", async () => {
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      items: [],
      total: 0,
      limit: 8,
      offset: 0,
    } satisfies Page<StockListItem>);
    vi.mocked(stocksApi.discoverSecurities).mockRejectedValue(new Error("provider down"));
    const user = userEvent.setup();

    renderSearch();
    await user.type(screen.getByRole("combobox"), "AMD");

    expect(await screen.findByText(/live discovery is unavailable/i)).toBeInTheDocument();
  });
});
