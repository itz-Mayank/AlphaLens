import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as portfolioApi from "./api";
import { PortfoliosPage } from "./PortfoliosPage";
import type { Portfolio } from "./types";

vi.mock("./api");

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/app/portfolio"]}>
        <Routes>
          <Route path="/app/portfolio" element={<PortfoliosPage />} />
          <Route path="/app/portfolio/:portfolioId" element={<div>Detail placeholder</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PortfoliosPage", () => {
  beforeEach(() => {
    vi.mocked(portfolioApi.listPortfolios).mockReset();
    vi.mocked(portfolioApi.createPortfolio).mockReset();
  });

  it("shows an empty state when there are no portfolios", async () => {
    vi.mocked(portfolioApi.listPortfolios).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText(/no portfolios yet/i)).toBeInTheDocument();
  });

  it("renders portfolios from the API", async () => {
    const portfolio: Portfolio = {
      id: "p1",
      name: "Main Brokerage",
      description: null,
      base_currency: "USD",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
    };
    vi.mocked(portfolioApi.listPortfolios).mockResolvedValue([portfolio]);

    renderPage();

    expect(await screen.findByText("Main Brokerage")).toBeInTheDocument();
  });

  it("creates a portfolio via the form", async () => {
    vi.mocked(portfolioApi.listPortfolios).mockResolvedValue([]);
    vi.mocked(portfolioApi.createPortfolio).mockResolvedValue({
      id: "p2",
      name: "Retirement",
      description: null,
      base_currency: "USD",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/no portfolios yet/i);

    await user.type(screen.getByPlaceholderText(/main brokerage/i), "Retirement");
    await user.click(screen.getByRole("button", { name: /create portfolio/i }));

    expect(portfolioApi.createPortfolio).toHaveBeenCalledWith({ name: "Retirement" });
  });
});
