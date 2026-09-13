from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.cache import DASHBOARD_OVERVIEW_TTL_SECONDS, cache_get_json, cache_set_json
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.dashboard import DashboardOverview
from app.services.dashboard_service import build_dashboard_overview

router = APIRouter()

_CACHE_KEY = "dashboard:overview"


@router.get("/overview", response_model=DashboardOverview)
def get_dashboard_overview(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DashboardOverview:
    """Market summary, movers, sector performance, breadth, and recent
    activity — see app/services/dashboard_service.py for the exact
    methodology behind each figure. Not user-specific, so one cache entry
    serves every viewer (ADR in decisions.md)."""
    cached = cache_get_json(_CACHE_KEY)
    if cached is not None:
        return DashboardOverview.model_validate(cached)

    overview = build_dashboard_overview(db)
    cache_set_json(
        _CACHE_KEY, overview.model_dump(mode="json"), ttl_seconds=DASHBOARD_OVERVIEW_TTL_SECONDS
    )
    return overview
