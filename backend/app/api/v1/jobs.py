import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import NotFoundError
from app.db.models.user import User
from app.db.session import get_db
from app.repositories.job_repository import JobRepository
from app.schemas.market_data import JobRead

router = APIRouter()


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> JobRead:
    job = JobRepository(db).get_by_id(job_id)
    if job is None:
        raise NotFoundError(f"No job found with id '{job_id}'.", code="JOB_NOT_FOUND")
    return JobRead.model_validate(job)
