from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

# dashboard_service.compute_freshness_status returns exactly this type.
FreshnessStatus = Literal["current", "stale", "outdated", "no_data"]
BreadthStatus = Literal["ok", "unavailable"]


class MarketSummary(BaseModel):
    total_securities: int
    securities_with_price_data: int
    latest_market_data_ts: datetime | None
    data_sources: list[str]
    freshness_status: FreshnessStatus


class MoverItem(BaseModel):
    ticker: str
    name: str
    sector: str | None
    last_price: Decimal
    change_percent: Decimal
    volume: int


class ActiveItem(BaseModel):
    ticker: str
    name: str
    sector: str | None
    last_price: Decimal
    volume: int


class MarketMovers(BaseModel):
    as_of: datetime | None
    top_gainers: list[MoverItem]
    top_losers: list[MoverItem]
    most_active: list[ActiveItem]


class SectorPerformance(BaseModel):
    sector: str
    security_count: int
    securities_with_data: int
    average_return_percent: Decimal | None


class SectorOverview(BaseModel):
    as_of: datetime | None
    sectors: list[SectorPerformance]


class MarketBreadth(BaseModel):
    as_of: datetime | None
    status: BreadthStatus
    advancing: int | None
    declining: int | None
    unchanged: int | None
    no_data: int


class RecentActivityItem(BaseModel):
    ticker: str
    name: str
    last_price: Decimal
    as_of: datetime


class DashboardOverview(BaseModel):
    market_summary: MarketSummary
    market_movers: MarketMovers
    sector_overview: SectorOverview
    market_breadth: MarketBreadth
    recent_activity: list[RecentActivityItem]
