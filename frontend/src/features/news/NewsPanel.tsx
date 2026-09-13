import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { formatRelativeDate } from "@/lib/format";

import { getStockNews } from "./api";
import type { SentimentLabel } from "./types";

interface NewsPanelProps {
  ticker: string;
}

const SENTIMENT_TONE: Record<SentimentLabel, string> = {
  positive: "text-bullish bg-bullish/10 border-bullish/30",
  negative: "text-bearish bg-bearish/10 border-bearish/30",
  neutral: "text-muted bg-border/30 border-border",
};

export function NewsPanel({ ticker }: NewsPanelProps) {
  const newsQuery = useQuery({
    queryKey: ["news", ticker],
    queryFn: () => getStockNews(ticker, 10),
    retry: false,
  });

  return (
    <Card className="flex flex-col gap-3 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">Recent News</p>

      {newsQuery.isLoading && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      )}

      {newsQuery.isError && <ErrorState onRetry={() => newsQuery.refetch()} />}

      {newsQuery.isSuccess && newsQuery.data.articles.length === 0 && (
        <EmptyState
          title="No recent news"
          description="No articles have been mapped to this stock yet."
        />
      )}

      {newsQuery.isSuccess && newsQuery.data.articles.length > 0 && (
        <>
          {newsQuery.data.data_sources.includes("demo") && (
            <p className="rounded border border-warning/30 bg-warning/10 px-3 py-1.5 text-xs text-warning">
              Demo News — simulated articles, not real news coverage.
            </p>
          )}
          <ul className="flex flex-col divide-y divide-border">
            {newsQuery.data.articles.map((article) => (
              <li key={article.id} className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
                <a
                  href={article.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm font-medium text-foreground hover:underline"
                >
                  {article.title}
                </a>
                <div className="flex items-center gap-2 text-xs text-muted">
                  <span>{article.publisher}</span>
                  <span>·</span>
                  <span>{formatRelativeDate(article.published_at)}</span>
                  {article.sentiment && (
                    <span
                      className={clsx(
                        "ml-auto rounded border px-1.5 py-0.5 text-xs font-medium capitalize",
                        SENTIMENT_TONE[article.sentiment.predicted_label],
                      )}
                    >
                      {article.sentiment.predicted_label}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
