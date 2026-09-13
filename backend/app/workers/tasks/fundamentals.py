"""Celery task wrapper around app.services.fundamentals_service.run_ingestion.

Deliberately thin, mirroring app/workers/tasks/market_data.py: all real
logic lives in the service so it's testable without Celery.
"""

import uuid

from app.db.session import SessionLocal
from app.services.fundamentals_service import run_ingestion
from app.workers.celery_app import celery_app


@celery_app.task(name="fundamentals.ingest")
def ingest_fundamentals_task(job_id: str, ticker: str) -> None:
    db = SessionLocal()
    try:
        run_ingestion(db, job_id=uuid.UUID(job_id), ticker=ticker)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
