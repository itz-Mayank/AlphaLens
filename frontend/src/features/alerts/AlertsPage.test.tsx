import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as alertsApi from "./api";
import { AlertsPage } from "./AlertsPage";
import type { Alert } from "./types";

vi.mock("./api");

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AlertsPage />
    </QueryClientProvider>,
  );
}

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: "a1",
    ticker: "AAPL",
    alert_type: "PRICE_ABOVE",
    config: { threshold: 200 },
    enabled: true,
    cooldown_minutes: 60,
    last_triggered_at: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("AlertsPage", () => {
  beforeEach(() => {
    vi.mocked(alertsApi.listAlerts).mockReset();
    vi.mocked(alertsApi.createAlert).mockReset();
    vi.mocked(alertsApi.updateAlert).mockReset();
    vi.mocked(alertsApi.deleteAlert).mockReset();
    vi.mocked(alertsApi.listAlertEvents).mockReset();
  });

  it("shows an empty state when there are no alerts", async () => {
    vi.mocked(alertsApi.listAlerts).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText(/no alerts yet/i)).toBeInTheDocument();
  });

  it("describes a real alert condition honestly, never a fabricated trigger claim", async () => {
    vi.mocked(alertsApi.listAlerts).mockResolvedValue([makeAlert()]);

    renderPage();

    expect(await screen.findByText(/AAPL \/ Price above \$200/)).toBeInTheDocument();
    expect(screen.getByText(/never triggered yet/i)).toBeInTheDocument();
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
  });

  it("creates an alert with the typed config for the selected condition", async () => {
    vi.mocked(alertsApi.listAlerts).mockResolvedValue([]);
    vi.mocked(alertsApi.createAlert).mockResolvedValue(makeAlert());
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/no alerts yet/i);

    await user.type(screen.getByPlaceholderText("AAPL"), "aapl");
    await user.type(screen.getByLabelText(/threshold \(\$\)/i), "200");
    await user.click(screen.getByRole("button", { name: /create alert/i }));

    expect(alertsApi.createAlert).toHaveBeenCalledWith({
      ticker: "AAPL",
      config: { alert_type: "PRICE_ABOVE", threshold: 200 },
    });
  });

  it("toggles an alert's enabled state", async () => {
    vi.mocked(alertsApi.listAlerts).mockResolvedValue([makeAlert()]);
    vi.mocked(alertsApi.updateAlert).mockResolvedValue(makeAlert({ enabled: false }));
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/AAPL \/ Price above/);

    await user.click(screen.getByRole("button", { name: /pause/i }));

    expect(alertsApi.updateAlert).toHaveBeenCalledWith("a1", { enabled: false });
  });

  it("lazily loads and shows real trigger events only once expanded", async () => {
    vi.mocked(alertsApi.listAlerts).mockResolvedValue([makeAlert()]);
    vi.mocked(alertsApi.listAlertEvents).mockResolvedValue({
      items: [
        {
          id: "e1",
          triggered_at: "2026-01-05T00:00:00Z",
          observed_value: { price: 205 },
          message: "AAPL crossed above $200",
          created_at: "2026-01-05T00:00:00Z",
        },
      ],
      total: 1,
      limit: 5,
      offset: 0,
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/AAPL \/ Price above/);
    expect(alertsApi.listAlertEvents).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /show recent events/i }));

    expect(await screen.findByText("AAPL crossed above $200")).toBeInTheDocument();
    expect(alertsApi.listAlertEvents).toHaveBeenCalledWith("a1", 5, 0);
  });
});
