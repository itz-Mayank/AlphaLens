import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as screenerApi from "./api";
import { ScreenerPage } from "./ScreenerPage";
import type { ScreenerResponse, ScreenerRow } from "./types";

vi.mock("./api");

function makeRow(overrides: Partial<ScreenerRow> = {}): ScreenerRow {
  return {
    security_id: 1,
    ticker: "AAPL",
    name: "Apple Inc.",
    sector: "Technology",
    last_price: "150.00",
    change_percent: "1.25",
    volume: 1_000_000,
    return_20d_percent: 3.5,
    rsi_14: 55.2,
    forecast_direction: "Bullish",
    sentiment_score: 0.4,
    unavailable_fields: [],
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/app/screener"]}>
        <Routes>
          <Route path="/app/screener" element={<ScreenerPage />} />
          <Route path="/app/stocks/:ticker" element={<div>Detail placeholder</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ScreenerPage", () => {
  beforeEach(() => {
    vi.mocked(screenerApi.runScreener).mockReset();
  });

  it("shows an empty state when nothing matches", async () => {
    vi.mocked(screenerApi.runScreener).mockResolvedValue({
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
      forecast_available: true,
      forecast_unavailable_reason: null,
      disclaimer: "disclaimer text",
    } satisfies ScreenerResponse);

    renderPage();

    expect(await screen.findByText(/no matching stocks/i)).toBeInTheDocument();
  });

  it("renders real screener rows with forecast and sentiment, never fabricated placeholders", async () => {
    vi.mocked(screenerApi.runScreener).mockResolvedValue({
      items: [makeRow(), makeRow({ security_id: 2, ticker: "NODATA", forecast_direction: null, sentiment_score: null, unavailable_fields: ["forecast_direction", "sentiment_score"] })],
      total: 2,
      limit: 25,
      offset: 0,
      forecast_available: true,
      forecast_unavailable_reason: null,
      disclaimer: "disclaimer text",
    } satisfies ScreenerResponse);

    renderPage();

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    // "Bullish" also appears as a <select> option, so scope to the badge.
    expect(screen.getAllByText("Bullish").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("NODATA")).toBeInTheDocument();
    // Missing forecast/sentiment renders as "—", not a fabricated value.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });

  it("shows a warning banner when the forecast model is unavailable", async () => {
    vi.mocked(screenerApi.runScreener).mockResolvedValue({
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
      forecast_available: false,
      forecast_unavailable_reason: "No trained model is registered yet.",
      disclaimer: "disclaimer text",
    } satisfies ScreenerResponse);

    renderPage();

    expect(await screen.findByText(/no trained model is registered yet/i)).toBeInTheDocument();
  });

  it("re-queries the backend with the new sort column and direction on header click", async () => {
    vi.mocked(screenerApi.runScreener).mockResolvedValue({
      items: [makeRow()],
      total: 1,
      limit: 25,
      offset: 0,
      forecast_available: true,
      forecast_unavailable_reason: null,
      disclaimer: "disclaimer text",
    } satisfies ScreenerResponse);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("AAPL");
    vi.mocked(screenerApi.runScreener).mockClear();

    await user.click(screen.getByRole("columnheader", { name: /price/i }));

    await waitFor(() => {
      expect(screenerApi.runScreener).toHaveBeenCalledWith(
        expect.objectContaining({ sort_by: "last_price", sort_direction: "asc" }),
      );
    });

    await user.click(screen.getByRole("columnheader", { name: /price/i }));

    await waitFor(() => {
      expect(screenerApi.runScreener).toHaveBeenCalledWith(
        expect.objectContaining({ sort_by: "last_price", sort_direction: "desc" }),
      );
    });
  });

  it("sends min/max range filters to the backend", async () => {
    vi.mocked(screenerApi.runScreener).mockResolvedValue({
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
      forecast_available: true,
      forecast_unavailable_reason: null,
      disclaimer: "disclaimer text",
    } satisfies ScreenerResponse);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/no matching stocks/i);
    vi.mocked(screenerApi.runScreener).mockClear();

    await user.type(screen.getByLabelText(/min price/i), "50");
    await user.type(screen.getByLabelText(/min 20d return/i), "5");

    await waitFor(() => {
      expect(screenerApi.runScreener).toHaveBeenCalledWith(
        expect.objectContaining({ min_price: 50, min_return_20d_percent: 5 }),
      );
    });
  });
});
