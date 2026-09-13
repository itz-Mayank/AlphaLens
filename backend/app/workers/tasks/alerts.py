"""Celery task wrapper around app.services.alert_evaluation_service.evaluate_all_alerts.

Deliberately thin, same shape as `market_data.py`/`news.py`: all real
evaluation logic lives in the service so it's testable without Celery.
Scheduled by Celery Beat (see `app/workers/celery_app.py`'s `beat_schedule`)
rather than triggered per-request — alert evaluation is a periodic sweep
over every enabled alert, not something a user's HTTP request kicks off.

Uses the generic `jobs` table (`JobType.ALERT_EVALUATION`) for observability
of each evaluation run, the same pattern ingestion jobs use — no new
tracking table for this.
"""

from app.db.models.job import JobType
from app.db.session import SessionLocal
from app.repositories.job_repository import JobRepository
from app.services.alert_evaluation_service import evaluate_all_alerts
from app.workers.celery_app import celery_app


@celery_app.task(name="alerts.evaluate")
def evaluate_alerts_task() -> None:
    db = SessionLocal()
    jobs = JobRepository(db)
    job = jobs.create(job_type=JobType.ALERT_EVALUATION, requested_by_user_id=None)
    jobs.mark_running(job)
    db.commit()
    try:
        summary = evaluate_all_alerts(db)
        db.commit()
        jobs.mark_completed(
            job,
            metadata={
                "evaluated": summary.evaluated,
                "triggered": summary.triggered,
                "skipped_cooldown": summary.skipped_cooldown,
                "skipped_no_data": summary.skipped_no_data,
                "errors": summary.errors,
            },
        )
        db.commit()
    except Exception as exc:
        # Only the evaluation work (any alert triggers/state updates not
        # yet flushed) is rolled back here — the job row was already
        # committed above, so it can still be marked failed below.
        db.rollback()
        jobs.mark_failed(job, error=str(exc))
        db.commit()
        raise
    finally:
        db.close()
