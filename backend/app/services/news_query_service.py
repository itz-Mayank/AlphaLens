"""Read-side news/sentiment queries for the API layer — thin composition
over `NewsRepository` + `news_sentiment_aggregation`, no business logic of
its own beyond assembling a response shape. No fake articles, no fake
sentiment: every field here traces back to a stored `NewsArticle`/
`NewsSentiment` row or is explicitly `None`/empty when there isn't one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ml.nlp.sentiment import MODEL_REVISION
from sqlalchemy.orm import Session

from app.db.models.security import Security
from app.repositories.news_repository import NewsRepository
from app.services import news_sentiment_aggregation as aggregation

DEFAULT_NEWS_LIMIT = 20
SENTIMENT_HISTORY_DAYS = 30


def _sentiment_dict(sentiment) -> dict | None:  # noqa: ANN001 - NewsSentiment ORM row or None
    if sentiment is None:
        return None
    return {
        "positive_prob": float(sentiment.positive_prob),
        "neutral_prob": float(sentiment.neutral_prob),
        "negative_prob": float(sentiment.negative_prob),
        "predicted_label": sentiment.predicted_label,
        "model_name": sentiment.model_name,
        "model_version": sentiment.model_version,
        "processed_at": sentiment.processed_at,
    }


def get_recent_news(db: Session, *, security: Security, limit: int = DEFAULT_NEWS_LIMIT) -> dict:
    repo = NewsRepository(db)
    articles = repo.get_articles_for_security(security_id=security.id, limit=limit)
    sentiment_by_article = repo.get_sentiment_by_article_id(
        [a.id for a in articles], model_version=MODEL_REVISION
    )
    return {
        "ticker": security.ticker,
        "articles": [
            {
                "id": a.id,
                "title": a.title,
                "summary": a.summary,
                "url": a.url,
                "publisher": a.publisher,
                "published_at": a.published_at,
                "data_source": a.data_source,
                "sentiment": _sentiment_dict(sentiment_by_article.get(a.id)),
            }
            for a in articles
        ],
        "data_sources": sorted({a.data_source for a in articles}),
    }


def get_sentiment_overview(db: Session, *, security: Security) -> dict:
    as_of = datetime.now(UTC)
    last_24h = aggregation.compute_sentiment_summary(
        db, security_id=security.id, as_of=as_of, window_days=1, model_version=MODEL_REVISION
    )
    last_7d = aggregation.compute_sentiment_summary(
        db, security_id=security.id, as_of=as_of, window_days=7, model_version=MODEL_REVISION
    )
    return {
        "ticker": security.ticker,
        "last_24h": last_24h.as_dict(),
        "last_7d": last_7d.as_dict(),
        "model_version": MODEL_REVISION,
    }


def get_sentiment_history(
    db: Session, *, security: Security, days: int = SENTIMENT_HISTORY_DAYS
) -> dict:
    as_of = datetime.now(UTC)
    points = []
    for offset in range(days):
        day_end = as_of - timedelta(days=offset)
        day_start = day_end - timedelta(days=1)
        stats = aggregation.compute_window_stats(
            db,
            security_id=security.id,
            since=day_start,
            until=day_end,
            model_version=MODEL_REVISION,
        )
        points.append(
            {
                "date": day_end.date(),
                "article_count": stats.article_count,
                "positive_count": stats.positive_count,
                "neutral_count": stats.neutral_count,
                "negative_count": stats.negative_count,
                "average_sentiment_score": stats.average_sentiment_score,
            }
        )
    points.reverse()  # oldest first, for charting
    return {"ticker": security.ticker, "points": points, "model_version": MODEL_REVISION}
