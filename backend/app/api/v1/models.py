from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.errors import NotFoundError
from app.db.models.job import JobType
from app.db.models.user import User, UserRole
from app.db.session import get_db
from app.repositories.job_repository import JobRepository
from app.repositories.security_repository import SecurityRepository
from app.schemas.model_registry import (
    DriftReportItem,
    DriftResponse,
    LivePerformanceResponse,
    ModelRecordRead,
    RetrainTriggerResponse,
)
from app.services import drift_service, model_registry_service, prediction_service
from app.workers.tasks.retraining import retrain_models_task

router = APIRouter()

# Model-lifecycle data (registry contents, live performance, drift,
# retraining) is operational/internal — ANALYST/ADMIN only, same
# restriction as triggering ingestion (app/api/v1/market_data.py).
_OPS_ROLES = (UserRole.ANALYST, UserRole.ADMIN)


@router.get("", response_model=list[ModelRecordRead])
def list_models(
    _user: User = Depends(require_roles(*_OPS_ROLES)),
) -> list[ModelRecordRead]:
    """Every registered model record — every training run, every
    promotion/rejection decision, exactly as `ml.registry.registry` has
    them. Never filtered to "the good ones" — a FAILED or ARCHIVED record
    is real history, not noise to hide."""
    return [ModelRecordRead(**record) for record in model_registry_service.list_all_models()]


@router.get("/{model_type}/performance", response_model=LivePerformanceResponse)
def get_model_performance(
    model_type: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(*_OPS_ROLES)),
) -> LivePerformanceResponse:
    """LIVE, observed performance from this deployment's own matured
    predictions for `model_type` — never this model's training/backtest
    metrics (see GET /models for those). See
    app/services/prediction_service.py's module docstring for why the two
    are never combined."""
    report = prediction_service.get_live_performance(db, model_type=model_type)
    return LivePerformanceResponse(
        model_type=report.model_type,
        insufficient_data=report.insufficient_data,
        reason=report.reason,
        sample_count=report.sample_count,
        mae=report.mae,
        rmse=report.rmse,
        directional_hit_rate=report.directional_hit_rate,
        directional_sample_count=report.directional_sample_count,
        disclaimer=report.disclaimer,
    )


@router.get("/drift/{ticker}", response_model=DriftResponse)
def get_drift_report(
    ticker: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(*_OPS_ROLES)),
) -> DriftResponse:
    security = SecurityRepository(db).get_by_ticker(ticker)
    if security is None:
        raise NotFoundError(
            f"No stock found for ticker '{ticker.upper()}'.", code="STOCK_NOT_FOUND"
        )
    reports = drift_service.compute_drift_report(db, security)
    return DriftResponse(
        ticker=security.ticker,
        reports=[DriftReportItem(**vars(r)) for r in reports],
    )


@router.post("/retrain", response_model=RetrainTriggerResponse, status_code=202)
def trigger_retraining(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*_OPS_ROLES)),
) -> RetrainTriggerResponse:
    """Enqueues a full retraining run against the real bundled research
    dataset. Never runs training synchronously in the request — this only
    creates a `jobs` row and hands it to Celery; see
    app/services/retraining_service.py for the actual (background-only)
    work and app/registry/promotion.py for why training succeeding never
    implies the result becomes servable."""
    job = JobRepository(db).create(
        job_type=JobType.MODEL_RETRAINING,
        requested_by_user_id=user.id,
    )
    db.flush()
    job_id = job.id
    # Commit before enqueueing — see market_data.py's identical comment on
    # the dispatch-before-commit race this avoids.
    db.commit()

    retrain_models_task.delay(str(job_id))

    return RetrainTriggerResponse(job_id=str(job_id), status=job.status)
