import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class NewsIngestRequest(BaseModel):
    tickers: list[str] | None = Field(
        default=None, description="Tickers to fetch news for, or omit for the full known universe."
    )
    since: datetime | None = None

    @field_validator("tickers")
    @classmethod
    def _uppercase_tickers(cls, value: list[str] | None) -> list[str] | None:
        return [t.upper() for t in value] if value else value


class NewsIngestResponse(BaseModel):
    job_id: uuid.UUID
    status: str


class ArticleSentimentRead(BaseModel):
    positive_prob: float
    neutral_prob: float
    negative_prob: float
    predicted_label: str
    model_name: str
    model_version: str
    processed_at: datetime


class NewsArticleRead(BaseModel):
    id: int
    title: str
    summary: str | None
    url: str
    publisher: str
    published_at: datetime
    data_source: str
    sentiment: ArticleSentimentRead | None


class NewsListResponse(BaseModel):
    ticker: str
    articles: list[NewsArticleRead]
    data_sources: list[str]


class SentimentSummaryRead(BaseModel):
    as_of: datetime
    window_days: float
    since: datetime
    until: datetime
    article_count: int
    positive_count: int
    neutral_count: int
    negative_count: int
    average_sentiment_score: float | None
    sentiment_momentum: float | None


class SentimentOverviewResponse(BaseModel):
    ticker: str
    last_24h: SentimentSummaryRead
    last_7d: SentimentSummaryRead
    model_version: str
    disclaimer: str = (
        "Sentiment is an informational signal derived from recent news coverage — it is not a "
        "guaranteed trading signal and has not been shown to predict this security's future return."
    )


class SentimentHistoryPoint(BaseModel):
    date: date
    article_count: int
    positive_count: int
    neutral_count: int
    negative_count: int
    average_sentiment_score: float | None


class SentimentHistoryResponse(BaseModel):
    ticker: str
    points: list[SentimentHistoryPoint]
    model_version: str
