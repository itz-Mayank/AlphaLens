import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";

import * as agentApi from "./api";
import { ChatPage } from "./ChatPage";
import type { ChatResponse } from "./types";

vi.mock("./api");

function makeResponse(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    conversation_id: "conv-1",
    answer: "AAPL is trading near its latest close. [Market Data]",
    evidence: [
      {
        source_type: "MARKET_DATA",
        source_id: "quote:AAPL",
        ticker: "AAPL",
        timestamp: "2026-09-11T00:00:00Z",
        data: { last_price: 190.12 },
        provenance: "demo",
      },
    ],
    citations: ["[Market Data]"],
    tools_used: ["get_stock_quote"],
    tool_calls: [{ name: "get_stock_quote", ok: true, latency_ms: 12.3 }],
    model: "fake-model-v1",
    provider: "fake",
    request_id: "req-1",
    prompt_version: "v1",
    disclaimer: "AlphaLens Research Assistant — analytical and educational only, not financial advice.",
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ChatPage />
    </QueryClientProvider>,
  );
}

function typeAndSend(message: string) {
  fireEvent.change(screen.getByPlaceholderText(/ask a research question/i), {
    target: { value: message },
  });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));
}

describe("ChatPage", () => {
  beforeEach(() => {
    vi.mocked(agentApi.postChat).mockReset();
  });

  it("shows suggested questions, each backed by a real tool, before any message is sent", () => {
    renderPage();
    expect(screen.getByText(/try one of these/i)).toBeInTheDocument();
    expect(screen.getByText("Explain the latest MSFT forecast")).toBeInTheDocument();
    expect(screen.getByText("Run a backtest for MSFT")).toBeInTheDocument();
  });

  it("sends a suggested question immediately when clicked", async () => {
    vi.mocked(agentApi.postChat).mockResolvedValue(makeResponse());

    renderPage();
    fireEvent.click(screen.getByText("Show recent MSFT sentiment"));

    expect(screen.getByText("Show recent MSFT sentiment")).toBeInTheDocument();
    await screen.findByText("AAPL is trading near its latest close. [Market Data]");
    expect(agentApi.postChat).toHaveBeenCalledWith(
      { message: "Show recent MSFT sentiment", conversation_id: null },
      expect.anything(),
    );
  });

  it("sends a message and renders the grounded answer with citations and evidence", async () => {
    vi.mocked(agentApi.postChat).mockResolvedValue(makeResponse());

    renderPage();
    typeAndSend("What's AAPL's current price?");

    expect(screen.getByText("What's AAPL's current price?")).toBeInTheDocument();
    expect(
      await screen.findByText("AAPL is trading near its latest close. [Market Data]"),
    ).toBeInTheDocument();
    expect(screen.getByText("[Market Data]")).toBeInTheDocument();
    expect(screen.getByText("Evidence (1)")).toBeInTheDocument();

    expect(agentApi.postChat).toHaveBeenCalledWith(
      { message: "What's AAPL's current price?", conversation_id: null },
      expect.anything(),
    );
  });

  it("renders the assistant's markdown answer instead of showing raw syntax", async () => {
    vi.mocked(agentApi.postChat).mockResolvedValue(
      makeResponse({ answer: "**RSI (14-day)** for AAPL: **56.36** [Technical Indicators]" }),
    );

    renderPage();
    typeAndSend("What's AAPL's RSI?");

    const strongEl = await screen.findByText("RSI (14-day)");
    expect(strongEl.tagName).toBe("STRONG");
    expect(screen.queryByText(/\*\*RSI/)).not.toBeInTheDocument();
  });

  it("expanding the evidence details shows the source type and ticker", async () => {
    vi.mocked(agentApi.postChat).mockResolvedValue(makeResponse());

    renderPage();
    typeAndSend("What's AAPL's current price?");
    await screen.findByText("Evidence (1)");
    fireEvent.click(screen.getByText("Evidence (1)"));

    expect(screen.getByText("Market Data")).toBeInTheDocument(); // exact text of the evidence badge, not the "[Market Data]" citation tag
    expect(screen.getAllByText(/AAPL/).length).toBeGreaterThan(0);
  });

  it("carries the returned conversation_id into the next request", async () => {
    vi.mocked(agentApi.postChat).mockResolvedValue(makeResponse({ conversation_id: "conv-42" }));

    renderPage();
    typeAndSend("What's AAPL's current price?");
    await screen.findByText(/trading near its latest close/i);

    vi.mocked(agentApi.postChat).mockResolvedValue(
      makeResponse({
        conversation_id: "conv-42",
        answer: "Still steady.",
        citations: [],
        request_id: "req-2",
      }),
    );
    typeAndSend("Anything new?");

    await screen.findByText("Still steady.");
    expect(agentApi.postChat).toHaveBeenLastCalledWith(
      { message: "Anything new?", conversation_id: "conv-42" },
      expect.anything(),
    );
  });

  it("shows a readable message for a known error code", async () => {
    vi.mocked(agentApi.postChat).mockRejectedValue(
      new ApiError(503, "AGENT_UNAVAILABLE", "no llm configured"),
    );

    renderPage();
    typeAndSend("What's AAPL's current price?");

    expect(
      await screen.findByText(/research assistant is temporarily unavailable/i),
    ).toBeInTheDocument();
  });

  it("shows a distinct message for a rate limit, not the generic unavailable copy", async () => {
    vi.mocked(agentApi.postChat).mockRejectedValue(
      new ApiError(429, "HTTP_ERROR", "20 per 1 hour"),
    );

    renderPage();
    typeAndSend("What's AAPL's current price?");

    expect(await screen.findByText(/reached the hourly limit/i)).toBeInTheDocument();
    expect(screen.queryByText(/temporarily unavailable/i)).not.toBeInTheDocument();
  });

  it("shows real tool-call activity on a grounded answer", async () => {
    vi.mocked(agentApi.postChat).mockResolvedValue(makeResponse());

    renderPage();
    typeAndSend("What's AAPL's current price?");

    expect(await screen.findByText(/get_stock_quote/)).toBeInTheDocument();
  });

  it("shows a generic message for an unexpected failure", async () => {
    vi.mocked(agentApi.postChat).mockRejectedValue(new Error("network down"));

    renderPage();
    typeAndSend("What's AAPL's current price?");

    expect(
      await screen.findByText(/something went wrong reaching the research assistant/i),
    ).toBeInTheDocument();
  });

  it("disables the send button until there is input", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText(/ask a research question/i), {
      target: { value: "hi" },
    });
    expect(screen.getByRole("button", { name: /send/i })).not.toBeDisabled();
  });

  it("sends the message on Enter but not on Shift+Enter", async () => {
    vi.mocked(agentApi.postChat).mockResolvedValue(makeResponse());
    renderPage();
    const textarea = screen.getByPlaceholderText(/ask a research question/i);

    fireEvent.change(textarea, { target: { value: "hello" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(agentApi.postChat).not.toHaveBeenCalled();

    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    // `mutate()` invokes `mutationFn` on a microtask, not synchronously — wait
    // for the full round trip (including the state update in onSuccess) so
    // the test doesn't finish mid-flight and trigger an act() warning.
    await screen.findByText("AAPL is trading near its latest close. [Market Data]");
    expect(agentApi.postChat).toHaveBeenCalledTimes(1);
  });
});
