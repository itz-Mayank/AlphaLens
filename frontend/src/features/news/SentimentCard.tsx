import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";

import { getStockSentiment } from "./api";
import type { SentimentSummary } from "./types";

interface SentimentCardProps {
  ticker: string;
}

function formatScore(value: number | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function overallTone(summary: SentimentSummary): string {
  if (summary.average_sentiment_score === null) return "text-muted";
  if (summary.average_sentiment_score > 0.05) return "text-bullish";
  if (summary.average_sentiment_score < -0.05) return "text-bearish";
  return "text-muted";
}

export function SentimentCard({ ticker }: SentimentCardProps) {
  const sentimentQuery = useQuery({
    queryKey: ["sentiment", ticker],
    queryFn: () => getStockSentiment(ticker),
    retry: false,
  });

  if (sentimentQuery.isLoading) {
    return (
      <Card className="p-4">
        <Skeleton className="h-32 w-full" />
      </Card>
    );
  }

  if (sentimentQuery.isError) {
    return (
      <Card className="p-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
          Sentiment Overview
        </p>
        <ErrorState onRetry={() => sentimentQuery.refetch()} />
      </Card>
    );
  }

  const data = sentimentQuery.data;
  if (!data) return null;

  if (data.last_7d.article_count === 0) {
    return (
      <Card className="p-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
          Sentiment Overview
        </p>
        <EmptyState
          title="No sentiment data yet"
          description="No processed news articles are available for this stock."
        />
      </Card>
    );
  }

  const { last_7d } = data;
  const total = last_7d.positive_count + last_7d.neutral_count + last_7d.negative_count;

  return (
    <Card className="flex flex-col gap-3 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">Sentiment Overview</p>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <p className="text-xs text-muted">7-day score</p>
          <p className={`text-lg font-semibold ${overallTone(last_7d)}`}>
            {formatScore(last_7d.average_sentiment_score)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Articles (7d)</p>
          <p className="text-lg font-semibold">{last_7d.article_count}</p>
        </div>
        <div>
          <p className="text-xs text-muted">24h score</p>
          <p className={`text-lg font-semibold ${overallTone(data.last_24h)}`}>
            {formatScore(data.last_24h.average_sentiment_score)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Momentum</p>
          <p className="text-lg font-semibold">{formatScore(last_7d.sentiment_momentum)}</p>
        </div>
      </div>

      {total > 0 && (
        <div className="flex h-2 overflow-hidden rounded-full bg-border/40">
          <div
            className="bg-bullish"
            style={{ width: `${(last_7d.positive_count / total) * 100}%` }}
          />
          <div className="bg-border" style={{ width: `${(last_7d.neutral_count / total) * 100}%` }} />
          <div
            className="bg-bearish"
            style={{ width: `${(last_7d.negative_count / total) * 100}%` }}
          />
        </div>
      )}
      <div className="flex gap-3 text-xs text-muted">
        <span>{last_7d.positive_count} positive</span>
        <span>{last_7d.neutral_count} neutral</span>
        <span>{last_7d.negative_count} negative</span>
      </div>

      <p className="text-xs text-muted">{data.disclaimer}</p>
    </Card>
  );
}
