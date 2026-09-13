"""Tests for `app/services/retraining_service.py`'s job-observability
wrapper and duplicate-delivery guard — never the real (multi-minute)
training run itself, which is covered separately and expensively by
`ml/tests/integration/test_train_pipeline_integration.py`. `run_experiment`
is monkeypatched to a fast fake so these run in the normal suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.db.models.job import Job, JobStatus, JobType
from app.repositories.job_repository import JobRepository
from app.services import retraining_service


@dataclass
class _FakeProvenance:
    dataset_version: str = "fake-dataset-v1"


@dataclass
class _FakeExperimentResult:
    output_dir: Path
    provenance: _FakeProvenance = field(default_factory=_FakeProvenance)


def _create_job(db_session) -> Job:
    job = JobRepository(db_session).create(
        job_type=JobType.MODEL_RETRAINING, requested_by_user_id=None
    )
    db_session.flush()
    return job


def test_run_retraining_completes_the_job_on_success(db_session, monkeypatch, tmp_path):
    job = _create_job(db_session)
    monkeypatch.setattr(
        retraining_service,
        "run_experiment",
        lambda config, output_dir: _FakeExperimentResult(output_dir=output_dir),
    )

    retraining_service.run_retraining(db_session, job_id=job.id)

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.extra["dataset_version"] == "fake-dataset-v1"


def test_run_retraining_marks_the_job_failed_on_a_real_exception(db_session, monkeypatch):
    job = _create_job(db_session)

    def _boom(config, output_dir):
        raise RuntimeError("training blew up")

    monkeypatch.setattr(retraining_service, "run_experiment", _boom)

    retraining_service.run_retraining(db_session, job_id=job.id)

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "training blew up" in job.error


def test_run_retraining_is_a_no_op_for_an_unknown_job_id(db_session, monkeypatch):
    import uuid

    calls = []
    monkeypatch.setattr(
        retraining_service, "run_experiment", lambda config, output_dir: calls.append(1)
    )
    retraining_service.run_retraining(db_session, job_id=uuid.uuid4())
    assert calls == []


class TestDuplicateDeliveryGuard:
    """`task_acks_late=True` (ADR-043) can redeliver the same Celery task
    message — this guard makes a redelivered duplicate a no-op instead of a
    second, colliding training run against the same `registry.json` file."""

    def test_a_job_already_running_is_skipped_not_re_run(self, db_session, monkeypatch):
        job = _create_job(db_session)
        JobRepository(db_session).mark_running(job)
        db_session.flush()
        original_started_at = job.started_at

        calls = []
        monkeypatch.setattr(
            retraining_service, "run_experiment", lambda config, output_dir: calls.append(1)
        )

        retraining_service.run_retraining(db_session, job_id=job.id)

        assert calls == []  # training was never re-invoked
        db_session.refresh(job)
        assert job.status == JobStatus.RUNNING  # untouched, not reset/re-completed
        assert job.started_at == original_started_at

    def test_an_already_completed_job_is_not_re_run(self, db_session, monkeypatch):
        job = _create_job(db_session)
        JobRepository(db_session).mark_running(job)
        JobRepository(db_session).mark_completed(job, metadata={"dataset_version": "v1"})
        db_session.flush()

        calls = []
        monkeypatch.setattr(
            retraining_service, "run_experiment", lambda config, output_dir: calls.append(1)
        )

        retraining_service.run_retraining(db_session, job_id=job.id)

        assert calls == []
        db_session.refresh(job)
        assert job.extra["dataset_version"] == "v1"  # unchanged by the skipped duplicate

    def test_a_freshly_queued_job_still_runs_normally(self, db_session, monkeypatch):
        """The guard must only skip non-QUEUED jobs — a genuine first
        delivery (the normal case) must still proceed."""
        job = _create_job(db_session)
        assert job.status == JobStatus.QUEUED

        monkeypatch.setattr(
            retraining_service,
            "run_experiment",
            lambda config, output_dir: _FakeExperimentResult(output_dir=output_dir),
        )

        retraining_service.run_retraining(db_session, job_id=job.id)

        db_session.refresh(job)
        assert job.status == JobStatus.COMPLETED
