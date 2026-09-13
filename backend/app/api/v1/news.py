from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.models.job import JobType
from app.db.models.user import User, UserRole
from app.db.session import get_db
from app.repositories.job_repository import JobRepository
from app.schemas.news import NewsIngestRequest, NewsIngestResponse
from app.workers.tasks.news import ingest_news_task

router = APIRouter()


@router.post("/ingest", response_model=NewsIngestResponse, status_code=202)
def trigger_news_ingestion(
    payload: NewsIngestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ANALYST, UserRole.ADMIN)),
) -> NewsIngestResponse:
    """Enqueues a news ingestion + sentiment-processing job. Restricted to
    ANALYST/ADMIN, same rationale as `/market-data/ingest`: triggering
    ingestion (and the FinBERT inference it runs) is an operational
    action, not something every USER should be able to do on demand.
    """
    job = JobRepository(db).create(
        job_type=JobType.NEWS_INGESTION,
        requested_by_user_id=user.id,
        metadata={"requested_tickers": payload.tickers},
    )
    db.flush()
    job_id = job.id
    # Commit before enqueueing — see app/api/v1/market_data.py's identical
    # comment: the worker runs in a separate process/connection and may
    # start on this job before the request finishes otherwise.
    db.commit()

    ingest_news_task.delay(
        str(job_id),
        payload.tickers,
        payload.since.isoformat() if payload.since else None,
    )

    return NewsIngestResponse(job_id=job_id, status=job.status)
