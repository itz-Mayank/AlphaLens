from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.providers import MacroObservationRead, MacroSeriesResponse
from app.services import macro_service

router = APIRouter()


@router.get("/{series_id}", response_model=MacroSeriesResponse)
def get_macro_series(
    series_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> MacroSeriesResponse:
    """Never 404s on an unrecognized `series_id` — a macro series isn't a
    tracked entity the way a security is, so an unknown/not-yet-ingested
    series is reported as `available=False`, same as one that exists but
    has no data yet."""
    report = macro_service.get_macro_series(db, series_id=series_id.upper())
    return MacroSeriesResponse(
        series_id=report.series_id,
        available=report.available,
        reason=report.reason,
        source=report.source,
        observations=[MacroObservationRead(**vars(o)) for o in report.observations],
    )
