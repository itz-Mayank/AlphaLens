import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class WatchlistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class WatchlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class WatchlistListItem(WatchlistRead):
    item_count: int


class WatchlistItemAdd(BaseModel):
    ticker: str = Field(..., max_length=10)


class WatchlistItemRead(BaseModel):
    security_id: int
    ticker: str
    name: str
    sector: str | None
    last_price: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None
    volume: int | None
    as_of: str | None
    data_unavailable: bool


class WatchlistDetailResponse(WatchlistRead):
    items: list[WatchlistItemRead]
