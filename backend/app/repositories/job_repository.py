import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.job import Job, JobStatus


class JobRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        job_type: str,
        requested_by_user_id: uuid.UUID | None,
        security_id: int | None = None,
        metadata: dict | None = None,
    ) -> Job:
        job = Job(
            job_type=job_type,
            requested_by_user_id=requested_by_user_id,
            security_id=security_id,
            extra=metadata,
        )
        self.db.add(job)
        self.db.flush()
        return job

    def get_by_id(self, job_id: uuid.UUID) -> Job | None:
        return self.db.get(Job, job_id)

    def get_by_id_locked(self, job_id: uuid.UUID) -> Job | None:
        """Same as `get_by_id`, but with `SELECT ... FOR UPDATE` — for a
        task whose work is NOT naturally idempotent under Celery's
        at-least-once delivery (`task_acks_late=True` can redeliver the
        same task message). A second worker that picks up a redelivered
        message blocks here until the first's transaction commits, then
        sees the job's real (non-`QUEUED`) status and can skip re-running
        it — the same pattern `alert_evaluation_service.py` uses for its
        own concurrent-evaluation race (ADR-039)."""
        stmt = select(Job).where(Job.id == job_id).with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    def mark_running(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)

    def mark_completed(self, job: Job, *, metadata: dict | None = None) -> None:
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        if metadata is not None:
            job.extra = {**(job.extra or {}), **metadata}

    def mark_failed(self, job: Job, *, error: str) -> None:
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(UTC)
        job.error = error

    def get_latest_by_type(self, job_type: str) -> Job | None:
        """Most recently created job of `job_type`, regardless of status —
        backs provider health reporting (last attempt, whatever its
        outcome), not just "last success"."""
        stmt = (
            select(Job)
            .where(Job.job_type == job_type)
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_completed_by_type(self, job_type: str) -> Job | None:
        stmt = (
            select(Job)
            .where(Job.job_type == job_type, Job.status == JobStatus.COMPLETED)
            .order_by(Job.completed_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_failed_by_type(self, job_type: str) -> Job | None:
        stmt = (
            select(Job)
            .where(Job.job_type == job_type, Job.status == JobStatus.FAILED)
            .order_by(Job.completed_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()
