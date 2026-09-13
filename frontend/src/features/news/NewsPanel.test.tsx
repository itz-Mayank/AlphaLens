import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as newsApi from "./api";
import { NewsPanel } from "./NewsPanel";
import type { NewsArticle, NewsListResponse } from "./types";

vi.mock("./api");

function makeArticle(overrides: Partial<NewsArticle> = {}): NewsArticle {
  return {
    id: 1,
    title: "Company reports record quarterly profits",
    summary: "The company beat analyst expectations.",
    url: "https://demo-news.invalid/aapl/0",
    publisher: "Demo Wire",
    published_at: "2026-09-10T12:00:00Z",
    data_source: "demo",
    sentiment: {
      positive_prob: 0.9,
      neutral_prob: 0.05,
      negative_prob: 0.05,
      predicted_label: "positive",
      model_name: "ProsusAI/finbert",
      model_version: "abc123",
      processed_at: "2026-09-10T13:00:00Z",
    },
    ...overrides,
  };
}

function renderPanel(ticker = "AAPL") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <NewsPanel ticker={ticker} />
    </QueryClientProvider>,
  );
}

describe("NewsPanel", () => {
  beforeEach(() => {
    vi.mocked(newsApi.getStockNews).mockReset();
  });

  it("renders articles with headline, publisher, and sentiment", async () => {
    const response: NewsListResponse = {
      ticker: "AAPL",
      articles: [makeArticle()],
      data_sources: ["demo"],
    };
    vi.mocked(newsApi.getStockNews).mockResolvedValue(response);

    renderPanel();

    expect(await screen.findByText("Company reports record quarterly profits")).toBeInTheDocument();
    expect(screen.getByText("Demo Wire")).toBeInTheDocument();
    expect(screen.getByText("positive")).toBeInTheDocument();
    expect(screen.getByText(/demo news/i)).toBeInTheDocument();
  });

  it("links each article to its real url", async () => {
    vi.mocked(newsApi.getStockNews).mockResolvedValue({
      ticker: "AAPL",
      articles: [makeArticle()],
      data_sources: ["demo"],
    });

    renderPanel();

    const link = await screen.findByRole("link", { name: /record quarterly profits/i });
    expect(link).toHaveAttribute("href", "https://demo-news.invalid/aapl/0");
  });

  it("shows an empty state when there are no articles", async () => {
    vi.mocked(newsApi.getStockNews).mockResolvedValue({
      ticker: "AAPL",
      articles: [],
      data_sources: [],
    });

    renderPanel();

    expect(await screen.findByText("No recent news")).toBeInTheDocument();
  });

  it("shows a retryable error state on failure", async () => {
    vi.mocked(newsApi.getStockNews).mockRejectedValue(new Error("boom"));

    renderPanel();

    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("renders an article with no sentiment yet without a sentiment badge", async () => {
    vi.mocked(newsApi.getStockNews).mockResolvedValue({
      ticker: "AAPL",
      articles: [makeArticle({ sentiment: null })],
      data_sources: ["demo"],
    });

    renderPanel();

    await screen.findByText("Company reports record quarterly profits");
    expect(screen.queryByText("positive")).not.toBeInTheDocument();
  });

  it("does not show the demo banner when all articles are external", async () => {
    vi.mocked(newsApi.getStockNews).mockResolvedValue({
      ticker: "AAPL",
      articles: [makeArticle({ data_source: "external" })],
      data_sources: ["external"],
    });

    renderPanel();

    await screen.findByText("Company reports record quarterly profits");
    expect(screen.queryByText(/demo news/i)).not.toBeInTheDocument();
  });
});
