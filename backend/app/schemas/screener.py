from decimal import Decimal

from pydantic import BaseModel


class ScreenerRowRead(BaseModel):
    security_id: int
    ticker: str
    name: str
    sector: str | None
    last_price: Decimal | None
    change_percent: Decimal | None
    volume: int | None
    return_20d_percent: float | None
    rsi_14: float | None
    forecast_direction: str | None
    sentiment_score: float | None
    unavailable_fields: list[str]


class ScreenerResponse(BaseModel):
    items: list[ScreenerRowRead]
    total: int
    limit: int
    offset: int
    forecast_available: bool
    forecast_unavailable_reason: str | None
    disclaimer: str = (
        "Screener fields reflect this deployment's own data only — see "
        "each stock's data_source. A field is null (never a fabricated "
        "zero) when it genuinely could not be computed, e.g. insufficient "
        "price history for a 20-day return, or a ticker outside the "
        "forecast model's trained universe."
    )
