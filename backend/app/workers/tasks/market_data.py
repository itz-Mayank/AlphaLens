"""Celery task wrapper around app.services.market_data_service.run_ingestion.

Deliberately thin: all real logic lives in the service so it's testable
without Celery. This module's only job is DB session lifecycle + handing
off to that function.
"""

import uuid
from datetime import date

from app.db.session import SessionLocal
from app.services.market_data_service import run_ingestion
from app.workers.celery_app import celery_app


@celery_app.task(name="market_data.ingest")
def ingest_market_data_task(
    job_id: str,
    tickers: list[str] | None,
    start_date: str | None,
    end_date: str | None,
) -> None:
    db = SessionLocal()
    try:
        run_ingestion(
            db,
            job_id=uuid.UUID(job_id),
            tickers=tickers,
            start_date=date.fromisoformat(start_date) if start_date else None,
            end_date=date.fromisoformat(end_date) if end_date else None,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
