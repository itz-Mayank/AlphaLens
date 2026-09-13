import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SecurityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    name: str
    exchange: str
    sector: str | None
    industry: str | None
    currency: str
    status: str
    data_source: str


class StockListItem(SecurityRead):
    last_price: Decimal | None = None
    change: Decimal | None = None
    change_percent: Decimal | None = None
    volume: int | None = None
    as_of: datetime | None = None


class StockDetailResponse(StockListItem):
    week_52_high: Decimal | None = None
    week_52_low: Decimal | None = None


class PriceBarRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int


class PriceHistoryResponse(BaseModel):
    ticker: str
    data_source: str
    bars: list[PriceBarRead]


class SecurityDiscoveryResult(BaseModel):
    """A live match from the configured market-data provider's own
    discovery/search capability — not a row from AlphaLens's own
    `securities` table. `already_tracked` tells the frontend whether
    selecting this result can go straight to the Research Workspace, or
    needs an ingest step first."""

    ticker: str
    name: str
    exchange: str
    currency: str
    already_tracked: bool


class IngestRequest(BaseModel):
    tickers: list[str] | None = Field(
        default=None, description="Tickers to ingest, or omit/null to ingest the full universe."
    )
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("tickers")
    @classmethod
    def _uppercase_tickers(cls, value: list[str] | None) -> list[str] | None:
        return [t.upper() for t in value] if value else value


class IngestResponse(BaseModel):
    job_id: uuid.UUID
    status: str


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    extra: dict | None
    created_at: datetime
