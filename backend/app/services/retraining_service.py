"""Background retraining orchestration.

This is the ONE module in `backend/app` allowed to import `ml.config`/
`ml.pipelines` (training code) — see ADR-001's boundary, extended by
Phase 10's explicit rule that training may run in the background (a
Celery task calling this module) but never inside a request handler. This
module itself does no HTTP/FastAPI work and is never imported by anything
under `app/api/`; only `app/workers/tasks/retraining.py` calls it — see
`tests/unit/test_architecture_boundaries.py`'s structural enforcement of
that rule.

Retraining never trains on every request, never blocks an API response,
and never auto-promotes a bad model — see `ml.registry.promotion` for the
actual gate; this module just wires "run one experiment" +
"run its candidates through the gate" together as one background unit of
work, using the SAME real bundled research dataset
`ml/scripts/run_real_experiment.py` uses (never fabricated data).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ml.config import ExperimentConfig
from ml.pipelines.train_pipeline import run_experiment
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models.job import JobStatus
from app.repositories.job_repository import JobRepository

logger = get_logger(__name__)


def run_retraining(db: Session, *, job_id: uuid.UUID) -> None:
    """Runs one full training experiment against the real bundled research
    dataset and records the outcome on the `jobs` row — same
    create-then-run-then-complete-or-fail shape as
    `market_data_service.run_ingestion`. The experiment's own
    `run_experiment` call already registers every model and runs the
    promotion gate (see `ml.pipelines.train_pipeline` /
    `ml.registry.promotion`) — this function adds no separate training or
    promotion logic of its own, only the job-observability wrapper.

    Unlike ingestion (idempotent via upsert), running a training experiment
    twice for the SAME job is not free: `ml.registry.registry` writes
    `registry.json` as a plain, unlocked file, so two concurrent runs
    racing to append a record could lose one's update. `task_acks_late`
    means Celery can redeliver the same task message at least once (e.g. a
    worker that appears lost but wasn't) — `get_by_id_locked` + a
    `QUEUED`-only guard makes a redelivered duplicate a no-op rather than a
    second, colliding training run, mirroring `alert_evaluation_service`'s
    own row-lock guard for its analogous concurrency concern (ADR-039).
    This does NOT protect against two DIFFERENT retraining jobs (two
    separate `POST /models/retrain` calls) running concurrently — see
    docs/decisions.md's Phase 10 finalization ADR for why that's an
    accepted limitation rather than new locking infrastructure for a
    manual, administrative-only, rarely-concurrent endpoint.
    """
    jobs = JobRepository(db)
    job = jobs.get_by_id_locked(job_id)
    if job is None:
        return
    if job.status != JobStatus.QUEUED:
        logger.warning(
            "retraining_duplicate_delivery_skipped", job_id=str(job_id), status=job.status
        )
        return
    jobs.mark_running(job)
    db.flush()

    try:
        settings = get_settings()
        registry_root = Path(settings.ml_registry_path).parent
        output_dir = registry_root / f"retrain_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"

        result = run_experiment(ExperimentConfig(), output_dir)

        decisions_path = output_dir / "promotion_decisions.json"
        promotion_decisions = (
            json.loads(decisions_path.read_text()) if decisions_path.exists() else {}
        )
        jobs.mark_completed(
            job,
            metadata={
                "output_dir": str(result.output_dir),
                "dataset_version": result.provenance.dataset_version,
                "promotion_decisions": promotion_decisions,
            },
        )
    except Exception as exc:  # noqa: BLE001 — a job must record failure, never raise to the caller
        jobs.mark_failed(job, error=str(exc))

    db.flush()
