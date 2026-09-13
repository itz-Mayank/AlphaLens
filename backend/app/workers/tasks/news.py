"""Celery task wrapper around app.services.news_sentiment_service.run_news_ingestion.

Deliberately thin: all real logic (fetch/normalize/dedupe/store/extract/
analyze) lives in the service so it's testable without Celery. This
module's only job is DB session lifecycle + handing off to that function —
same shape as `app/workers/tasks/market_data.py`.
"""

import uuid
from datetime import datetime

from app.db.session import SessionLocal
from app.services.news_sentiment_service import run_news_ingestion
from app.workers.celery_app import celery_app


@celery_app.task(name="news.ingest")
def ingest_news_task(
    job_id: str,
    tickers: list[str] | None,
    since: str | None,
) -> None:
    db = SessionLocal()
    try:
        run_news_ingestion(
            db,
            job_id=uuid.UUID(job_id),
            tickers=tickers,
            since=datetime.fromisoformat(since) if since else None,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
