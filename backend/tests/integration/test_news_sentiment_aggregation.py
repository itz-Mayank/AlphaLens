"""Integration tests for `app/services/news_sentiment_aggregation.py` —
real Postgres, real rows. `TestTemporalLeakage` is the CRITICAL suite
required for Phase 7: a prediction at `as_of` must never be influenced by
an article published after it.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models.news import ArticleSecurity, ContentStatus, NewsArticle, NewsSentiment
from app.db.models.security import Security
from app.services.news_sentiment_aggregation import compute_sentiment_summary, compute_window_stats

MODEL_VERSION = "test-model-v1"


def _security(db_session, ticker: str = "AAA") -> Security:
    s = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(s)
    db_session.flush()
    return s


def _article(db_session, *, external_id: str, published_at: datetime) -> NewsArticle:
    a = NewsArticle(
        source="test",
        external_id=external_id,
        title=f"Headline {external_id}",
        summary=None,
        url="https://demo-news.invalid/x",
        publisher="Test Wire",
        published_at=published_at,
        retrieved_at=published_at,
        language="en",
        content_status=ContentStatus.TITLE_ONLY,
        data_source="demo",
    )
    db_session.add(a)
    db_session.flush()
    return a


def _link(db_session, article: NewsArticle, security: Security) -> None:
    db_session.add(
        ArticleSecurity(
            article_id=article.id,
            security_id=security.id,
            match_method="TICKER_SYMBOL",
            confidence=Decimal("0.95"),
        )
    )
    db_session.flush()


def _sentiment(
    db_session,
    article: NewsArticle,
    *,
    label: str,
    positive: float,
    neutral: float,
    negative: float,
    model_version: str = MODEL_VERSION,
) -> None:
    db_session.add(
        NewsSentiment(
            article_id=article.id,
            model_name="test-model",
            model_version=model_version,
            positive_prob=Decimal(str(positive)),
            neutral_prob=Decimal(str(neutral)),
            negative_prob=Decimal(str(negative)),
            predicted_label=label,
            processed_at=datetime.now(UTC),
        )
    )
    db_session.flush()


def _add_article_with_sentiment(
    db_session, security, *, external_id, published_at, label, positive, neutral, negative
):
    article = _article(db_session, external_id=external_id, published_at=published_at)
    _link(db_session, article, security)
    _sentiment(
        db_session, article, label=label, positive=positive, neutral=neutral, negative=negative
    )
    return article


class TestTemporalLeakage:
    """A prediction/aggregate at `as_of`/`until` must never use information
    published after it."""

    def test_articles_published_after_as_of_are_excluded(self, db_session):
        security = _security(db_session)
        as_of = datetime(2026, 9, 10, tzinfo=UTC)

        _add_article_with_sentiment(
            db_session,
            security,
            external_id="past",
            published_at=as_of - timedelta(days=1),
            label="positive",
            positive=0.9,
            neutral=0.05,
            negative=0.05,
        )
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="future",
            published_at=as_of + timedelta(days=1),
            label="negative",
            positive=0.05,
            neutral=0.05,
            negative=0.9,
        )

        stats = compute_window_stats(
            db_session,
            security_id=security.id,
            since=as_of - timedelta(days=7),
            until=as_of,
            model_version=MODEL_VERSION,
        )

        assert stats.article_count == 1
        assert stats.positive_count == 1
        assert stats.negative_count == 0

    def test_articles_published_before_since_are_excluded(self, db_session):
        security = _security(db_session)
        since = datetime(2026, 9, 1, tzinfo=UTC)
        until = datetime(2026, 9, 8, tzinfo=UTC)

        _add_article_with_sentiment(
            db_session,
            security,
            external_id="too_old",
            published_at=since - timedelta(days=1),
            label="positive",
            positive=0.9,
            neutral=0.05,
            negative=0.05,
        )
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="in_window",
            published_at=since + timedelta(days=1),
            label="neutral",
            positive=0.3,
            neutral=0.4,
            negative=0.3,
        )

        stats = compute_window_stats(
            db_session,
            security_id=security.id,
            since=since,
            until=until,
            model_version=MODEL_VERSION,
        )

        assert stats.article_count == 1
        assert stats.neutral_count == 1

    def test_moving_as_of_forward_can_only_add_articles_never_remove(self, db_session):
        """Directly proves the boundary matters: the same underlying data,
        queried with a later `until`, must include everything the earlier
        query did plus the newly-in-range article — never fewer."""
        security = _security(db_session)
        as_of = datetime(2026, 9, 10, tzinfo=UTC)

        _add_article_with_sentiment(
            db_session,
            security,
            external_id="day0",
            published_at=as_of,
            label="positive",
            positive=0.8,
            neutral=0.1,
            negative=0.1,
        )
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="day2",
            published_at=as_of + timedelta(days=2),
            label="negative",
            positive=0.1,
            neutral=0.1,
            negative=0.8,
        )

        earlier = compute_window_stats(
            db_session,
            security_id=security.id,
            since=as_of - timedelta(days=7),
            until=as_of,
            model_version=MODEL_VERSION,
        )
        later = compute_window_stats(
            db_session,
            security_id=security.id,
            since=as_of - timedelta(days=7),
            until=as_of + timedelta(days=2),
            model_version=MODEL_VERSION,
        )

        assert earlier.article_count == 1
        assert later.article_count == 2

    def test_window_boundaries_are_inclusive(self, db_session):
        security = _security(db_session)
        since = datetime(2026, 9, 1, tzinfo=UTC)
        until = datetime(2026, 9, 8, tzinfo=UTC)

        _add_article_with_sentiment(
            db_session,
            security,
            external_id="at_since",
            published_at=since,
            label="neutral",
            positive=0.3,
            neutral=0.4,
            negative=0.3,
        )
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="at_until",
            published_at=until,
            label="neutral",
            positive=0.3,
            neutral=0.4,
            negative=0.3,
        )

        stats = compute_window_stats(
            db_session,
            security_id=security.id,
            since=since,
            until=until,
            model_version=MODEL_VERSION,
        )

        assert stats.article_count == 2

    def test_sentiment_momentum_only_uses_articles_within_the_window(self, db_session):
        """A future article far outside the window must not leak into the
        momentum calculation (recent-half vs. older-half of the window)."""
        security = _security(db_session)
        as_of = datetime(2026, 9, 10, tzinfo=UTC)

        # Older half: negative. Recent half: positive. Momentum should be positive.
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="older",
            published_at=as_of - timedelta(days=6),
            label="negative",
            positive=0.1,
            neutral=0.1,
            negative=0.8,
        )
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="recent",
            published_at=as_of - timedelta(days=1),
            label="positive",
            positive=0.8,
            neutral=0.1,
            negative=0.1,
        )
        # Far-future article that must not influence anything.
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="future",
            published_at=as_of + timedelta(days=30),
            label="negative",
            positive=0.0,
            neutral=0.0,
            negative=1.0,
        )

        summary = compute_sentiment_summary(
            db_session,
            security_id=security.id,
            as_of=as_of,
            window_days=7,
            model_version=MODEL_VERSION,
        )

        assert summary.stats.article_count == 2  # not 3 - the future article is excluded
        assert summary.sentiment_momentum is not None
        assert summary.sentiment_momentum > 0


class TestAggregationCorrectness:
    def test_empty_window_has_none_average_and_zero_counts(self, db_session):
        security = _security(db_session)
        stats = compute_window_stats(
            db_session,
            security_id=security.id,
            since=datetime(2026, 1, 1, tzinfo=UTC),
            until=datetime(2026, 1, 8, tzinfo=UTC),
            model_version=MODEL_VERSION,
        )
        assert stats.article_count == 0
        assert stats.average_sentiment_score is None

    def test_average_sentiment_score_is_mean_of_positive_minus_negative(self, db_session):
        security = _security(db_session)
        as_of = datetime(2026, 9, 10, tzinfo=UTC)
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="a",
            published_at=as_of,
            label="positive",
            positive=0.9,
            neutral=0.05,
            negative=0.05,
        )
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="b",
            published_at=as_of,
            label="negative",
            positive=0.1,
            neutral=0.1,
            negative=0.8,
        )

        stats = compute_window_stats(
            db_session,
            security_id=security.id,
            since=as_of - timedelta(days=1),
            until=as_of,
            model_version=MODEL_VERSION,
        )

        expected = ((0.9 - 0.05) + (0.1 - 0.8)) / 2
        assert stats.average_sentiment_score == expected

    def test_only_articles_with_sentiment_for_the_requested_model_version_count(self, db_session):
        """An article scored by a DIFFERENT model version must not be
        counted — model version is part of the identity, not
        interchangeable."""
        security = _security(db_session)
        as_of = datetime(2026, 9, 10, tzinfo=UTC)
        _add_article_with_sentiment(
            db_session,
            security,
            external_id="a",
            published_at=as_of,
            label="positive",
            positive=0.9,
            neutral=0.05,
            negative=0.05,
        )
        # Same article gets a second model version's sentiment too.
        article = db_session.query(NewsArticle).filter_by(external_id="a").one()
        _sentiment(
            db_session,
            article,
            label="neutral",
            positive=0.3,
            neutral=0.4,
            negative=0.3,
            model_version="other-model-v2",
        )

        stats = compute_window_stats(
            db_session,
            security_id=security.id,
            since=as_of - timedelta(days=1),
            until=as_of,
            model_version=MODEL_VERSION,
        )
        assert stats.article_count == 1
        assert stats.positive_count == 1

    def test_different_securities_are_isolated(self, db_session):
        aaa = _security(db_session, "AAA")
        bbb = _security(db_session, "BBB")
        as_of = datetime(2026, 9, 10, tzinfo=UTC)
        _add_article_with_sentiment(
            db_session,
            aaa,
            external_id="a",
            published_at=as_of,
            label="positive",
            positive=0.9,
            neutral=0.05,
            negative=0.05,
        )

        stats_bbb = compute_window_stats(
            db_session,
            security_id=bbb.id,
            since=as_of - timedelta(days=1),
            until=as_of,
            model_version=MODEL_VERSION,
        )
        assert stats_bbb.article_count == 0
