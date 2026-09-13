"""Celery task wrapper around app.services.macro_service.run_ingestion.

Deliberately thin, mirroring app/workers/tasks/market_data.py: all real
logic lives in the service so it's testable without Celery.
"""

import uuid
from datetime import date

from app.db.session import SessionLocal
from app.services.macro_service import run_ingestion
from app.workers.celery_app import celery_app


@celery_app.task(name="macro.ingest")
def ingest_macro_task(job_id: str, series_id: str, start: str, end: str) -> None:
    db = SessionLocal()
    try:
        run_ingestion(
            db,
            job_id=uuid.UUID(job_id),
            series_id=series_id,
            start=date.fromisoformat(start),
            end=date.fromisoformat(end),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
