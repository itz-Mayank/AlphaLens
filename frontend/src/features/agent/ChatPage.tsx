import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import clsx from "clsx";
import ReactMarkdown from "react-markdown";

import { Card } from "@/components/Card";
import { EvidenceCard } from "@/components/EvidenceCard";
import { PageHeader } from "@/components/PageHeader";
import { ApiError } from "@/lib/api-client";

import { postChat } from "./api";
import type { ChatTurn } from "./types";

// Only prompts a real, existing tool can actually answer (app/agent/tools.py):
// get_forecast/get_forecast_explanation, get_sentiment, run_backtest,
// get_watchlist. Never a suggestion the agent can't genuinely fulfill.
const SUGGESTED_QUESTIONS = [
  "Explain the latest MSFT forecast",
  "What are the strongest factors behind AAPL's forecast?",
  "Show recent MSFT sentiment",
  "Run a backtest for MSFT",
  "Show my watchlist signals",
];

// The agent's real answers come back as markdown (bold, lists, tables — see
// app/agent/llm_provider.py's prompting) — rendering it as plain text left
// literal "**"/"|" characters visible. react-markdown renders no raw HTML
// by default (no rehype-raw plugin), so this stays safe against anything
// adversarial that made it into a tool result's text (see docs/security.md
// prompt-injection defense) without needing manual sanitization.
const MARKDOWN_COMPONENTS = {
  p: (props: React.ComponentPropsWithoutRef<"p">) => <p className="mb-1.5 last:mb-0" {...props} />,
  ul: (props: React.ComponentPropsWithoutRef<"ul">) => (
    <ul className="mb-1.5 list-disc space-y-0.5 pl-4 last:mb-0" {...props} />
  ),
  ol: (props: React.ComponentPropsWithoutRef<"ol">) => (
    <ol className="mb-1.5 list-decimal space-y-0.5 pl-4 last:mb-0" {...props} />
  ),
  strong: (props: React.ComponentPropsWithoutRef<"strong">) => (
    <strong className="font-semibold text-foreground" {...props} />
  ),
  code: (props: React.ComponentPropsWithoutRef<"code">) => (
    <code className="rounded bg-border/40 px-1 py-0.5 font-mono text-xs" {...props} />
  ),
  a: (props: React.ComponentPropsWithoutRef<"a">) => (
    <a className="text-primary underline" target="_blank" rel="noreferrer" {...props} />
  ),
  table: (props: React.ComponentPropsWithoutRef<"table">) => (
    <div className="mb-1.5 overflow-x-auto">
      <table className="w-full border-collapse text-xs" {...props} />
    </div>
  ),
  th: (props: React.ComponentPropsWithoutRef<"th">) => (
    <th className="border-b border-border px-2 py-1 text-left font-medium text-muted" {...props} />
  ),
  td: (props: React.ComponentPropsWithoutRef<"td">) => (
    <td className="border-b border-border/60 px-2 py-1" {...props} />
  ),
};

function ChatBubble({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === "user";
  return (
    <div className={clsx("flex flex-col gap-2", isUser ? "items-end" : "items-start")}>
      <div
        className={clsx(
          "max-w-[85%] rounded-lg px-3 py-2 text-sm",
          isUser ? "whitespace-pre-wrap bg-primary text-white" : "border border-border bg-surface",
        )}
      >
        {isUser ? turn.text : <ReactMarkdown components={MARKDOWN_COMPONENTS}>{turn.text}</ReactMarkdown>}
      </div>
      {!isUser && turn.citations && turn.citations.length > 0 && (
        <div className="flex flex-wrap gap-1 text-xs text-muted">
          {turn.citations.map((tag) => (
            <span key={tag} className="rounded border border-border px-1.5 py-0.5">
              {tag}
            </span>
          ))}
        </div>
      )}
      {!isUser && turn.toolCalls && turn.toolCalls.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {turn.toolCalls.map((call, i) => (
            <span
              key={`${call.name}-${i}`}
              className={clsx(
                "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs",
                call.ok ? "border-border text-muted" : "border-bearish/40 text-bearish",
              )}
              title={`${call.ok ? "Succeeded" : "Failed"} in ${call.latency_ms.toFixed(0)}ms`}
            >
              {call.ok ? "✓" : "✕"} {call.name}
            </span>
          ))}
        </div>
      )}
      {!isUser && turn.evidence && turn.evidence.length > 0 && (
        <details className="w-full max-w-[85%] text-xs text-muted">
          <summary className="cursor-pointer select-none hover:text-foreground">
            Evidence ({turn.evidence.length})
          </summary>
          <div className="mt-1 flex flex-col gap-1">
            {turn.evidence.map((e) => (
              <EvidenceCard key={e.source_id} evidence={e} />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

/** Differentiates the ways `/research/chat` can fail rather than collapsing
 * everything into one generic message — a real bug (500), a genuine
 * environment-configuration state (503 AGENT_UNAVAILABLE), a rate limit
 * (429), and a validation problem (422) all mean different things and call
 * for different user actions. */
function ErrorPanel({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return (
        <div className="rounded border border-warning/30 bg-warning/5 px-3 py-2 text-sm text-warning">
          You've reached the hourly limit for research questions. Please try again later.
        </div>
      );
    }
    if (error.code === "AGENT_UNAVAILABLE") {
      return (
        <div className="rounded border border-warning/30 bg-warning/5 px-3 py-2 text-sm">
          <p className="font-medium text-warning">
            The research assistant is temporarily unavailable.
          </p>
          <p className="mt-1 text-xs text-muted">
            No LLM provider is configured for this deployment — an administrator needs to set an
            LLM API key. Details: {error.message}
          </p>
        </div>
      );
    }
    if (error.code === "VALIDATION_ERROR") {
      return <p className="text-sm text-bearish">Please enter a shorter message.</p>;
    }
    return <p className="text-sm text-bearish">{error.message}</p>;
  }
  return <p className="text-sm text-bearish">Something went wrong reaching the research assistant.</p>;
}

export function ChatPage() {
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);

  const chatMutation = useMutation({
    mutationFn: postChat,
    onSuccess: (response) => {
      setConversationId(response.conversation_id);
      setTurns((prev) => [
        ...prev,
        {
          id: response.request_id,
          role: "assistant",
          text: response.answer,
          citations: response.citations,
          evidence: response.evidence,
          toolsUsed: response.tools_used,
          toolCalls: response.tool_calls,
        },
      ]);
    },
  });

  function send(message: string) {
    const trimmed = message.trim();
    if (!trimmed || chatMutation.isPending) return;

    setTurns((prev) => [...prev, { id: crypto.randomUUID(), role: "user", text: trimmed }]);
    setInput("");
    chatMutation.mutate({ message: trimmed, conversation_id: conversationId });
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Research Assistant"
        description="Ask about forecasts, technical indicators, news, sentiment, watchlists, portfolios, alerts, or backtests. Every answer is grounded in AlphaLens's own data via cited tool calls — not a general-purpose chatbot, and not financial advice."
      />

      <Card className="flex min-h-[420px] flex-col gap-4 p-4">
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto">
          {turns.length === 0 && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted">Try one of these, or ask your own question:</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => send(q)}
                    className="rounded-full border border-border px-3 py-1.5 text-xs text-muted hover:border-primary hover:text-foreground"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((turn) => (
            <ChatBubble key={turn.id} turn={turn} />
          ))}
          {chatMutation.isPending && (
            <div className="flex items-start">
              <div className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-muted">
                Gathering evidence…
              </div>
            </div>
          )}
        </div>

        {chatMutation.isError && <ErrorPanel error={chatMutation.error} />}

        <div className="flex gap-2 border-t border-border pt-3">
          <textarea
            className="min-h-[44px] flex-1 resize-none rounded border border-border bg-transparent px-2 py-1.5 text-sm"
            placeholder="Ask a research question…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            maxLength={2000}
          />
          <button
            type="button"
            onClick={() => send(input)}
            disabled={chatMutation.isPending || !input.trim()}
            className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
          >
            Send
          </button>
        </div>
      </Card>

      <p className="text-xs text-muted">
        AlphaLens Research Assistant — analytical and educational only, not financial advice. Not a
        guarantee of future performance.
      </p>
    </div>
  );
}
