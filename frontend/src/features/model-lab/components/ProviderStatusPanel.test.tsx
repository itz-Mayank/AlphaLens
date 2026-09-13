import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/authStore";

import * as modelLabApi from "../api";
import type { ProviderStatus } from "../types";
import { ProviderStatusPanel } from "./ProviderStatusPanel";

vi.mock("../api");

function makeProvider(overrides: Partial<ProviderStatus> = {}): ProviderStatus {
  return {
    category: "market_data",
    configured_provider: "demo",
    credential_required: false,
    credential_configured: true,
    last_success_at: "2026-09-11T00:00:00Z",
    last_failure_at: null,
    last_failure_reason: null,
    last_latency_seconds: 0.42,
    ...overrides,
  };
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProviderStatusPanel />
    </QueryClientProvider>,
  );
}

const analystUser = {
  id: "1",
  email: "analyst@example.com",
  full_name: "Analyst",
  role: "ANALYST" as const,
  is_active: true,
  is_email_verified: true,
  created_at: "2026-01-01T00:00:00Z",
};

describe("ProviderStatusPanel", () => {
  beforeEach(() => {
    vi.mocked(modelLabApi.getProviderStatus).mockReset();
  });

  it("renders nothing for a plain USER, never issuing the 403-bound request", () => {
    useAuthStore.setState({ user: { ...analystUser, role: "USER" }, accessToken: "t", status: "authenticated" });

    const { container } = renderPanel();

    expect(container).toBeEmptyDOMElement();
    expect(modelLabApi.getProviderStatus).not.toHaveBeenCalled();
  });

  it("shows Demo for the demo market data provider, never labeling it Available", async () => {
    useAuthStore.setState({ user: analystUser, accessToken: "t", status: "authenticated" });
    vi.mocked(modelLabApi.getProviderStatus).mockResolvedValue({
      providers: [makeProvider()],
    });

    renderPanel();

    expect(await screen.findByText("Market Data")).toBeInTheDocument();
    expect(screen.getByText("Demo")).toBeInTheDocument();
  });

  it("shows Unconfigured for a provider with no credential, never claiming it's healthy", async () => {
    useAuthStore.setState({ user: analystUser, accessToken: "t", status: "authenticated" });
    vi.mocked(modelLabApi.getProviderStatus).mockResolvedValue({
      providers: [
        makeProvider({
          category: "fundamentals",
          configured_provider: "none",
          credential_required: false,
          credential_configured: true,
          last_success_at: null,
        }),
      ],
    });

    renderPanel();

    expect(await screen.findByText("Fundamentals")).toBeInTheDocument();
    expect(screen.getByText("Unconfigured")).toBeInTheDocument();
  });

  it("shows Unavailable with the real failure reason when the most recent attempt failed", async () => {
    useAuthStore.setState({ user: analystUser, accessToken: "t", status: "authenticated" });
    vi.mocked(modelLabApi.getProviderStatus).mockResolvedValue({
      providers: [
        makeProvider({
          category: "macro",
          configured_provider: "fred",
          credential_required: true,
          credential_configured: true,
          last_success_at: "2026-09-10T00:00:00Z",
          last_failure_at: "2026-09-11T00:00:00Z",
          last_failure_reason: "FRED API returned 401",
        }),
      ],
    });

    renderPanel();

    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("FRED API returned 401")).toBeInTheDocument();
  });
});
