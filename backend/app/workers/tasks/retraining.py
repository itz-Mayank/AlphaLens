"""Celery task wrapper around app.services.retraining_service.run_retraining.

Deliberately thin: all real orchestration lives in the service so it's
testable without Celery. Same shape as `market_data.py`'s ingestion task —
the router creates the `jobs` row and commits it before enqueueing (see
`app/api/v1/models.py`), and this task just hands `job_id` off to the
service, which manages its own running/completed/failed transitions.

Manually/administratively triggered only (`POST /models/retrain`,
ANALYST/ADMIN — see app/api/v1/models.py) — not on a Celery Beat schedule,
since retraining is compute-heavy with no natural fixed cadence this
deployment needs yet (see docs/decisions.md's Phase 10 ADR).
"""

import uuid

from app.db.session import SessionLocal
from app.services.retraining_service import run_retraining
from app.workers.celery_app import celery_app


@celery_app.task(name="models.retrain")
def retrain_models_task(job_id: str) -> None:
    db = SessionLocal()
    try:
        run_retraining(db, job_id=uuid.UUID(job_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
