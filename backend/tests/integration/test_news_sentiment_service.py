"""Integration test for `run_news_ingestion` — real Postgres, real (not
mocked) demo news provider, and REAL FinBERT inference. Mirrors
`test_market_data_service.py`'s shape exactly."""

from datetime import UTC, datetime, timedelta

import pytest
from app.db.models.job import Job, JobStatus, JobType
from app.db.models.news import ArticleSecurity, NewsArticle, NewsSentiment
from app.db.models.security import Security
from app.repositories.job_repository import JobRepository
from app.services.news_sentiment_service import run_news_ingestion
from ml.nlp.sentiment import MODEL_REVISION
from sqlalchemy import func, select

_NAMES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "JPM": "JPMorgan Chase & Co.",
}


def _create_job(db_session) -> Job:
    job = JobRepository(db_session).create(
        job_type=JobType.NEWS_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    return job


def _seed_securities(db_session, tickers: list[str]) -> None:
    for ticker in tickers:
        db_session.add(
            Security(ticker=ticker, name=_NAMES[ticker], exchange="NASDAQ", data_source="demo")
        )
    db_session.flush()


def test_run_news_ingestion_stores_articles_extracts_entities_and_scores_sentiment(db_session):
    _seed_securities(db_session, ["AAPL"])
    job = _create_job(db_session)
    since = datetime.now(UTC) - timedelta(days=7)

    run_news_ingestion(db_session, job_id=job.id, tickers=["AAPL"], since=since)

    articles = list(db_session.execute(select(NewsArticle)).scalars())
    assert len(articles) > 0
    assert all(a.data_source == "demo" for a in articles)

    security = db_session.execute(select(Security).where(Security.ticker == "AAPL")).scalar_one()
    matches = list(
        db_session.execute(
            select(ArticleSecurity).where(ArticleSecurity.security_id == security.id)
        ).scalars()
    )
    assert len(matches) == len(articles)  # every demo AAPL article mentions AAPL/Apple

    sentiment_rows = list(db_session.execute(select(NewsSentiment)).scalars())
    assert len(sentiment_rows) == len(articles)
    assert all(r.model_version == MODEL_REVISION for r in sentiment_rows)
    assert all(r.predicted_label in {"positive", "neutral", "negative"} for r in sentiment_rows)
    # Real inference, not hardcoded: the deliberately mixed-sentiment demo
    # headlines must produce more than one distinct predicted label.
    assert len({r.predicted_label for r in sentiment_rows}) > 1
    for row in sentiment_rows:
        total = float(row.positive_prob) + float(row.neutral_prob) + float(row.negative_prob)
        assert total == pytest.approx(1.0, abs=1e-4)

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.extra["articles_stored"] == len(articles)
    assert job.extra["sentiment_processed"] == len(articles)
    assert job.extra["sentiment_model_version"] == MODEL_REVISION


def test_run_news_ingestion_is_idempotent(db_session):
    _seed_securities(db_session, ["AAPL"])
    since = datetime.now(UTC) - timedelta(days=7)

    job1 = _create_job(db_session)
    run_news_ingestion(db_session, job_id=job1.id, tickers=["AAPL"], since=since)
    article_count_1 = db_session.execute(select(func.count()).select_from(NewsArticle)).scalar_one()
    sentiment_count_1 = db_session.execute(
        select(func.count()).select_from(NewsSentiment)
    ).scalar_one()

    job2 = _create_job(db_session)
    run_news_ingestion(db_session, job_id=job2.id, tickers=["AAPL"], since=since)
    article_count_2 = db_session.execute(select(func.count()).select_from(NewsArticle)).scalar_one()
    sentiment_count_2 = db_session.execute(
        select(func.count()).select_from(NewsSentiment)
    ).scalar_one()

    assert article_count_2 == article_count_1
    assert sentiment_count_2 == sentiment_count_1
    db_session.refresh(job2)
    assert job2.extra["sentiment_processed"] == 0  # nothing left to (re-)process


def test_run_news_ingestion_only_maps_entities_for_known_securities(db_session):
    """No `Security` row exists for TSLA in this test's DB — articles
    fetched about it must not invent a mapping."""
    job = _create_job(db_session)
    since = datetime.now(UTC) - timedelta(days=7)

    run_news_ingestion(db_session, job_id=job.id, tickers=["TSLA"], since=since)

    articles = list(db_session.execute(select(NewsArticle)).scalars())
    assert len(articles) > 0
    matches = list(db_session.execute(select(ArticleSecurity)).scalars())
    assert matches == []


def test_run_news_ingestion_marks_job_failed_on_error(db_session, monkeypatch):
    job = _create_job(db_session)

    def _boom(**kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        "app.services.news_sentiment_service.get_news_provider",
        lambda: type("BoomProvider", (), {"fetch_articles": staticmethod(_boom)})(),
    )

    run_news_ingestion(db_session, job_id=job.id, tickers=["AAPL"], since=None)

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "provider exploded" in job.error
