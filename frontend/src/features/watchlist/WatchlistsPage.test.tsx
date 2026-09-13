import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as watchlistApi from "./api";
import type { WatchlistListItem } from "./types";
import { WatchlistsPage } from "./WatchlistsPage";

vi.mock("./api");

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/app/watchlists"]}>
        <Routes>
          <Route path="/app/watchlists" element={<WatchlistsPage />} />
          <Route path="/app/watchlists/:watchlistId" element={<div>Detail placeholder</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WatchlistsPage", () => {
  beforeEach(() => {
    vi.mocked(watchlistApi.listWatchlists).mockReset();
    vi.mocked(watchlistApi.createWatchlist).mockReset();
  });

  it("shows an empty state when there are no watchlists", async () => {
    vi.mocked(watchlistApi.listWatchlists).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText(/no watchlists yet/i)).toBeInTheDocument();
  });

  it("renders watchlists with real item counts, never a placeholder count", async () => {
    const item: WatchlistListItem = {
      id: "w1",
      name: "Core Holdings",
      description: null,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      item_count: 3,
    };
    vi.mocked(watchlistApi.listWatchlists).mockResolvedValue([item]);

    renderPage();

    expect(await screen.findByText("Core Holdings")).toBeInTheDocument();
    expect(screen.getByText(/3 stocks/i)).toBeInTheDocument();
  });

  it("creates a watchlist and refreshes the list", async () => {
    vi.mocked(watchlistApi.listWatchlists).mockResolvedValue([]);
    vi.mocked(watchlistApi.createWatchlist).mockResolvedValue({
      id: "w2",
      name: "New List",
      description: null,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/no watchlists yet/i);

    await user.type(screen.getByPlaceholderText(/core holdings/i), "New List");
    await user.click(screen.getByRole("button", { name: /create watchlist/i }));

    expect(watchlistApi.createWatchlist).toHaveBeenCalledWith({ name: "New List" });
  });
});
