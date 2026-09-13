from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.models.job import JobType
from app.db.models.user import User, UserRole
from app.db.session import get_db
from app.repositories.job_repository import JobRepository
from app.schemas.market_data import IngestRequest, IngestResponse
from app.workers.tasks.market_data import ingest_market_data_task

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse, status_code=202)
def trigger_ingestion(
    payload: IngestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ANALYST, UserRole.ADMIN)),
) -> IngestResponse:
    """Enqueues a market-data ingestion job. Restricted to ANALYST/ADMIN —
    triggering ingestion against a (future) rate-limited external vendor is
    an operational action, not something every USER should be able to do.
    """
    job = JobRepository(db).create(
        job_type=JobType.MARKET_DATA_INGESTION,
        requested_by_user_id=user.id,
        metadata={"requested_tickers": payload.tickers},
    )
    db.flush()
    job_id = job.id
    # Commit before enqueueing: the worker runs in a separate process with
    # its own DB connection and may start on this job before the request
    # finishes otherwise, finding no such job row yet (classic
    # dispatch-before-commit race). get_db's own trailing commit becomes a
    # harmless no-op after this.
    db.commit()

    ingest_market_data_task.delay(
        str(job_id),
        payload.tickers,
        payload.start_date.isoformat() if payload.start_date else None,
        payload.end_date.isoformat() if payload.end_date else None,
    )

    return IngestResponse(job_id=job_id, status=job.status)
