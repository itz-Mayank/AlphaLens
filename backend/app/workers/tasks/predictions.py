"""Celery task wrapper around
app.services.prediction_service.evaluate_matured_predictions.

Deliberately thin, same shape as `alerts.py`. Scheduled daily via Celery
Beat (see `app/workers/celery_app.py`) — price bars in this deployment
only update once a day (Demo Mode's daily-bar ingestion), so checking
prediction maturity more often than that would find nothing new.
"""

from app.db.models.job import JobType
from app.db.session import SessionLocal
from app.repositories.job_repository import JobRepository
from app.services.prediction_service import evaluate_matured_predictions
from app.workers.celery_app import celery_app


@celery_app.task(name="predictions.evaluate")
def evaluate_predictions_task() -> None:
    db = SessionLocal()
    jobs = JobRepository(db)
    job = jobs.create(job_type=JobType.PREDICTION_EVALUATION, requested_by_user_id=None)
    jobs.mark_running(job)
    db.commit()
    try:
        summary = evaluate_matured_predictions(db)
        db.commit()
        jobs.mark_completed(
            job,
            metadata={
                "evaluated": summary.evaluated,
                "still_unmatured": summary.still_unmatured,
                "errors": summary.errors,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        jobs.mark_failed(job, error=str(exc))
        db.commit()
        raise
    finally:
        db.close()
