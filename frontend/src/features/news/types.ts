export type SentimentLabel = "positive" | "neutral" | "negative";

export interface ArticleSentiment {
  positive_prob: number;
  neutral_prob: number;
  negative_prob: number;
  predicted_label: SentimentLabel;
  model_name: string;
  model_version: string;
  processed_at: string;
}

export interface NewsArticle {
  id: number;
  title: string;
  summary: string | null;
  url: string;
  publisher: string;
  published_at: string;
  data_source: string;
  sentiment: ArticleSentiment | null;
}

export interface NewsListResponse {
  ticker: string;
  articles: NewsArticle[];
  data_sources: string[];
}

export interface SentimentSummary {
  as_of: string;
  window_days: number;
  since: string;
  until: string;
  article_count: number;
  positive_count: number;
  neutral_count: number;
  negative_count: number;
  average_sentiment_score: number | null;
  sentiment_momentum: number | null;
}

export interface SentimentOverviewResponse {
  ticker: string;
  last_24h: SentimentSummary;
  last_7d: SentimentSummary;
  model_version: string;
  disclaimer: string;
}

export interface SentimentHistoryPoint {
  date: string;
  article_count: number;
  positive_count: number;
  neutral_count: number;
  negative_count: number;
  average_sentiment_score: number | null;
}

export interface SentimentHistoryResponse {
  ticker: string;
  points: SentimentHistoryPoint[];
  model_version: string;
}
