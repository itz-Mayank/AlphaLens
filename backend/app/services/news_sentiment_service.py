"""News ingestion orchestration: fetch -> normalize -> dedupe -> store ->
entity-extract -> sentiment-analyze -> store.

Mirrors `app/services/market_data_service.py::run_ingestion`'s shape
exactly: a plain function, no Celery/FastAPI imports, called directly by
tests and wrapped thinly by `app/workers/tasks/news.py`. Sentiment
inference (`ml.nlp.sentiment`) is the one CPU-heavy step here — exactly
why this always runs via Celery, never inside an HTTP handler (see
docs/architecture.md "Background-job flow").
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from ml.nlp.sentiment import MODEL_REVISION, analyze_batch
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models.news import NewsArticle
from app.providers.base import NewsProvider
from app.providers.news import get_news_provider
from app.repositories.job_repository import JobRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.security_repository import SecurityRepository
from app.services.entity_extraction_service import extract_entities
from app.services.news_processing import (
    deduplicate_articles,
    filter_supported_language,
    normalize_article,
)

logger = get_logger(__name__)

DEFAULT_LOOKBACK_DAYS = 7
MAX_ARTICLES_PER_FETCH = 200
SENTIMENT_BATCH_SIZE = 16
NEWS_SOURCE_NAME = "demo_provider"


def _sentiment_text(article: NewsArticle) -> str:
    return f"{article.title}. {article.summary}" if article.summary else article.title


def run_news_ingestion(
    db: Session,
    *,
    job_id: uuid.UUID,
    tickers: list[str] | None,
    since: datetime | None,
    provider: NewsProvider | None = None,
) -> None:
    provider = provider or get_news_provider()
    jobs = JobRepository(db)
    news = NewsRepository(db)
    securities_repo = SecurityRepository(db)

    job = jobs.get_by_id(job_id)
    if job is None:
        logger.error("news_ingestion_job_not_found", job_id=str(job_id))
        return

    jobs.mark_running(job)
    db.flush()

    resolved_until = datetime.now(UTC)
    resolved_since = since or (resolved_until - timedelta(days=DEFAULT_LOOKBACK_DAYS))

    try:
        raw_articles = provider.fetch_articles(
            tickers=tickers,
            since=resolved_since,
            until=resolved_until,
            limit=MAX_ARTICLES_PER_FETCH,
        )
        normalized = [normalize_article(a) for a in raw_articles]
        supported, filtered_out = filter_supported_language(normalized)
        deduplicated = deduplicate_articles(supported)

        stored_articles = news.upsert_articles(
            source=NEWS_SOURCE_NAME, articles=deduplicated, data_source=provider.data_source
        )

        all_securities = securities_repo.list_all()
        entity_match_count = 0
        for article in stored_articles:
            matches = extract_entities(_sentiment_text(article), all_securities)
            news.add_entity_matches(article_id=article.id, matches=matches)
            entity_match_count += len(matches)

        pending = news.get_articles_missing_sentiment(model_version=MODEL_REVISION, limit=500)
        sentiment_processed = 0
        for batch_start in range(0, len(pending), SENTIMENT_BATCH_SIZE):
            batch = pending[batch_start : batch_start + SENTIMENT_BATCH_SIZE]
            results = analyze_batch([_sentiment_text(a) for a in batch])
            processed_at = datetime.now(UTC)
            for article, result in zip(batch, results, strict=True):
                news.upsert_sentiment(
                    article_id=article.id,
                    model_name=result.model_name,
                    model_version=result.model_version,
                    positive_prob=result.positive,
                    neutral_prob=result.neutral,
                    negative_prob=result.negative,
                    predicted_label=result.predicted_label,
                    processed_at=processed_at,
                )
            sentiment_processed += len(batch)

        db.flush()

        jobs.mark_completed(
            job,
            metadata={
                "tickers": tickers,
                "since": resolved_since.isoformat(),
                "until": resolved_until.isoformat(),
                "articles_fetched": len(raw_articles),
                "articles_filtered_language": len(filtered_out),
                "articles_deduplicated": len(supported) - len(deduplicated),
                "articles_stored": len(stored_articles),
                "entity_matches": entity_match_count,
                "sentiment_processed": sentiment_processed,
                "sentiment_model_version": MODEL_REVISION,
            },
        )
    except Exception as exc:  # noqa: BLE001 — a job must record failure, never raise to the caller
        logger.error("news_ingestion_failed", job_id=str(job_id), error=str(exc))
        jobs.mark_failed(job, error=str(exc))

    db.flush()
