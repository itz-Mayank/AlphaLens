"""Stock-level sentiment aggregation over a trailing time window.

CRITICAL — no temporal leakage: every query here is bounded by an explicit
`as_of` reference point, and only articles with `published_at <= as_of`
are ever included. A live API call resolves `as_of` to "now" at the
service-layer caller (mirrors `market_data_service.run_ingestion`'s
`end_date or datetime.now(UTC)` pattern) — this module itself never reads
wall-clock time, so a leakage test can pin `as_of` to a fixed point in the
past and prove articles published after it are excluded (see
`tests/unit/test_news_sentiment_aggregation.py::TestTemporalLeakage`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models.news import SentimentLabel
from app.repositories.news_repository import NewsRepository


@dataclass(frozen=True)
class SentimentWindowStats:
    since: datetime
    until: datetime
    article_count: int
    positive_count: int
    neutral_count: int
    negative_count: int
    # mean(positive_prob - negative_prob) across scored articles in the
    # window, in [-1, 1] — `None` (never 0) when there are zero scored
    # articles, since 0 is a real, meaningful "balanced" score.
    average_sentiment_score: float | None

    def as_dict(self) -> dict:
        return {
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "article_count": self.article_count,
            "positive_count": self.positive_count,
            "neutral_count": self.neutral_count,
            "negative_count": self.negative_count,
            "average_sentiment_score": self.average_sentiment_score,
        }


@dataclass(frozen=True)
class SentimentSummary:
    as_of: datetime
    window_days: float
    stats: SentimentWindowStats
    # `recent_half_average - older_half_average` within this window, both
    # halves computed independently — `None` if either half has zero
    # scored articles. Positive => sentiment trending up recently.
    sentiment_momentum: float | None

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "window_days": self.window_days,
            **self.stats.as_dict(),
            "sentiment_momentum": self.sentiment_momentum,
        }


def compute_window_stats(
    db: Session, *, security_id: int, since: datetime, until: datetime, model_version: str
) -> SentimentWindowStats:
    """The plain distribution/average for one explicit `[since, until]`
    window — no momentum, no window-length convention. Used directly by
    callers that need a simple per-period aggregate (e.g. one point in a
    daily sentiment-history series) without paying for
    `compute_sentiment_summary`'s extra momentum sub-queries."""
    repo = NewsRepository(db)
    articles = repo.get_articles_for_security(
        security_id=security_id, since=since, until=until, limit=1000
    )
    sentiment_by_article = repo.get_sentiment_by_article_id(
        [a.id for a in articles], model_version=model_version
    )
    sentiments = list(sentiment_by_article.values())

    positive_count = sum(1 for s in sentiments if s.predicted_label == SentimentLabel.POSITIVE)
    neutral_count = sum(1 for s in sentiments if s.predicted_label == SentimentLabel.NEUTRAL)
    negative_count = sum(1 for s in sentiments if s.predicted_label == SentimentLabel.NEGATIVE)

    average_sentiment_score = None
    if sentiments:
        average_sentiment_score = float(
            sum(float(s.positive_prob) - float(s.negative_prob) for s in sentiments)
            / len(sentiments)
        )

    return SentimentWindowStats(
        since=since,
        until=until,
        article_count=len(sentiments),
        positive_count=positive_count,
        neutral_count=neutral_count,
        negative_count=negative_count,
        average_sentiment_score=average_sentiment_score,
    )


def compute_sentiment_summary(
    db: Session, *, security_id: int, as_of: datetime, window_days: float, model_version: str
) -> SentimentSummary:
    """The full summary for one window ending at `as_of`: distribution,
    average score, and momentum (recent half of the window vs. the older
    half)."""
    since = as_of - timedelta(days=window_days)
    stats = compute_window_stats(
        db, security_id=security_id, since=since, until=as_of, model_version=model_version
    )

    half_days = window_days / 2
    midpoint = as_of - timedelta(days=half_days)
    recent = compute_window_stats(
        db, security_id=security_id, since=midpoint, until=as_of, model_version=model_version
    )
    older = compute_window_stats(
        db,
        security_id=security_id,
        since=midpoint - timedelta(days=half_days),
        until=midpoint,
        model_version=model_version,
    )
    momentum = None
    if recent.average_sentiment_score is not None and older.average_sentiment_score is not None:
        momentum = recent.average_sentiment_score - older.average_sentiment_score

    return SentimentSummary(
        as_of=as_of, window_days=window_days, stats=stats, sentiment_momentum=momentum
    )
