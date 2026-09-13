import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as newsApi from "./api";
import { SentimentCard } from "./SentimentCard";
import type { SentimentOverviewResponse, SentimentSummary } from "./types";

vi.mock("./api");

function makeSummary(overrides: Partial<SentimentSummary> = {}): SentimentSummary {
  return {
    as_of: "2026-09-11T00:00:00Z",
    window_days: 7,
    since: "2026-09-04T00:00:00Z",
    until: "2026-09-11T00:00:00Z",
    article_count: 8,
    positive_count: 5,
    neutral_count: 2,
    negative_count: 1,
    average_sentiment_score: 0.35,
    sentiment_momentum: 0.1,
    ...overrides,
  };
}

function makeResponse(
  overrides: Partial<SentimentOverviewResponse> = {},
): SentimentOverviewResponse {
  return {
    ticker: "AAPL",
    last_24h: makeSummary({
      window_days: 1,
      article_count: 2,
      positive_count: 1,
      neutral_count: 1,
      negative_count: 0,
      average_sentiment_score: 0.2,
      sentiment_momentum: 0.05,
    }),
    last_7d: makeSummary(),
    model_version: "abc123",
    disclaimer: "Sentiment is an informational signal, not a guaranteed trading signal.",
    ...overrides,
  };
}

function renderCard(ticker = "AAPL") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SentimentCard ticker={ticker} />
    </QueryClientProvider>,
  );
}

describe("SentimentCard", () => {
  beforeEach(() => {
    vi.mocked(newsApi.getStockSentiment).mockReset();
  });

  it("renders the 7-day score, article count, and distribution from the API", async () => {
    vi.mocked(newsApi.getStockSentiment).mockResolvedValue(makeResponse());

    renderCard();

    expect(await screen.findByText("+0.35")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("5 positive")).toBeInTheDocument();
    expect(screen.getByText("2 neutral")).toBeInTheDocument();
    expect(screen.getByText("1 negative")).toBeInTheDocument();
    expect(screen.getByText(/informational signal/i)).toBeInTheDocument();
  });

  it("shows an empty state when there is no sentiment data", async () => {
    vi.mocked(newsApi.getStockSentiment).mockResolvedValue(
      makeResponse({ last_7d: makeSummary({ article_count: 0, positive_count: 0, neutral_count: 0, negative_count: 0, average_sentiment_score: null, sentiment_momentum: null }) }),
    );

    renderCard();

    expect(await screen.findByText("No sentiment data yet")).toBeInTheDocument();
  });

  it("shows a retryable error state on failure", async () => {
    vi.mocked(newsApi.getStockSentiment).mockRejectedValue(new Error("boom"));

    renderCard();

    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
