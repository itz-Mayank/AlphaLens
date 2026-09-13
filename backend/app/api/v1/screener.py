from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.screener import ScreenerResponse, ScreenerRowRead
from app.services.screener_service import ScreenerFilters, run_screener

router = APIRouter()

_SORT_FIELDS = (
    "ticker", "last_price", "change_percent", "return_20d_percent", "volume", "rsi_14",
    "sentiment_score",
)


@router.get("", response_model=ScreenerResponse)
def get_screener_results(
    q: str | None = Query(default=None, description="Search by ticker or company name"),
    sector: str | None = Query(default=None),
    min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0),
    min_change_percent: Decimal | None = Query(default=None),
    max_change_percent: Decimal | None = Query(default=None),
    min_return_20d_percent: float | None = Query(default=None),
    max_return_20d_percent: float | None = Query(default=None),
    forecast_direction: str | None = Query(
        default=None, description="Bearish, Neutral, or Bullish"
    ),
    min_sentiment_score: float | None = Query(default=None, ge=-1, le=1),
    sort_by: str = Query(default="ticker", pattern="^(" + "|".join(_SORT_FIELDS) + ")$"),
    sort_direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ScreenerResponse:
    filters = ScreenerFilters(
        query=q,
        sector=sector,
        min_price=min_price,
        max_price=max_price,
        min_change_percent=min_change_percent,
        max_change_percent=max_change_percent,
        min_return_20d_percent=min_return_20d_percent,
        max_return_20d_percent=max_return_20d_percent,
        forecast_direction=forecast_direction,
        min_sentiment_score=min_sentiment_score,
        sort_by=sort_by,
        sort_direction=sort_direction,
        limit=limit,
        offset=offset,
    )
    result = run_screener(db, filters)
    return ScreenerResponse(
        items=[ScreenerRowRead(**vars(r)) for r in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        forecast_available=result.forecast_available,
        forecast_unavailable_reason=result.forecast_unavailable_reason,
    )
