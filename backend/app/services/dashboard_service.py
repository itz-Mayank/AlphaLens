"""Dashboard aggregation: market summary, movers, sector performance,
breadth, and recent activity — all derived from `securities` and
`price_bars`, never fabricated. See docs/decisions.md's Phase 4 ADR for the
full methodology writeup; the short version:

- **Reference period.** Movers, sector averages, and breadth all compare
  against the *same* date: the most recent `ts` present across all of
  `price_bars` ("as_of"). A security whose own latest bar is older than
  that (e.g. ingested with a narrower date range than the rest) is excluded
  from those three sections — comparing a security's move on one date
  against another's move on a different date isn't a real "market breadth"
  measure. It still appears in `market_summary` and `recent_activity`,
  which don't require a shared reference date.
- **Daily return.** `(close_t / close_{t-1} - 1) * 100`, computed from a
  security's two most recent bars ever (via `PriceBarRepository.
  get_latest_quotes`'s window-function `LAG`) — a real historical
  comparison, never look-ahead (there is no bar after "latest" to leak
  from). `None` (not `0`) when there's no previous bar or it's zero — a
  missing/undefined return must never render as "unchanged".
- **Sector average.** Equal-weighted mean of per-security daily returns
  among securities in that sector with a valid return as of the reference
  date. Not volume- or market-cap-weighted — there is no shares-outstanding
  data to weight by, and equal-weighting is the simplest methodology that
  doesn't fabricate a weighting scheme the data can't support.
- **No data still ships a real, honest state.** Every section has a
  defined shape when there's no ingested data yet (empty lists, `None`
  for undefined figures, `status: "unavailable"`/`"no_data"`) — never
  zeros standing in for "nothing to measure yet".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.price_bar_repository import LatestQuoteRow, PriceBarRepository
from app.repositories.security_repository import SecurityRepository
from app.schemas.dashboard import (
    ActiveItem,
    DashboardOverview,
    FreshnessStatus,
    MarketBreadth,
    MarketMovers,
    MarketSummary,
    MoverItem,
    RecentActivityItem,
    SectorOverview,
    SectorPerformance,
)
from app.services.market_data_service import compute_price_change

FRESHNESS_CURRENT_MAX_AGE_DAYS = 3
FRESHNESS_STALE_MAX_AGE_DAYS = 14
TOP_MOVERS_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 10


def compute_return_percent(close: Decimal, prev_close: Decimal | None) -> Decimal | None:
    """Delegates to `market_data_service.compute_price_change` — the one
    canonical formula, so this always agrees exactly with the same
    security's `change_percent` on `/stocks/{ticker}` (an earlier version
    duplicated the formula with a different-but-equivalent expression,
    which produced different values in the last few Decimal digits — a
    real cross-check between the two endpoints caught it)."""
    _, change_percent = compute_price_change(close, prev_close)
    return change_percent


def compute_freshness_status(latest_ts: datetime | None, *, now: datetime) -> FreshnessStatus:
    if latest_ts is None:
        return "no_data"
    age_days = (now - latest_ts).total_seconds() / 86400
    if age_days <= FRESHNESS_CURRENT_MAX_AGE_DAYS:
        return "current"
    if age_days <= FRESHNESS_STALE_MAX_AGE_DAYS:
        return "stale"
    return "outdated"


@dataclass(frozen=True)
class _RowWithReturn:
    row: LatestQuoteRow
    return_percent: Decimal  # only ever constructed for rows with a valid return


def build_dashboard_overview(db: Session, *, now: datetime | None = None) -> DashboardOverview:
    now = now or datetime.now(UTC)

    securities_repo = SecurityRepository(db)
    price_bars_repo = PriceBarRepository(db)

    total_securities = securities_repo.count_all()
    sector_counts = securities_repo.count_by_sector()
    data_sources = securities_repo.list_distinct_data_sources()

    quotes = price_bars_repo.get_latest_quotes()
    latest_market_data_ts = max((q.ts for q in quotes), default=None)

    market_summary = MarketSummary(
        total_securities=total_securities,
        securities_with_price_data=len(quotes),
        latest_market_data_ts=latest_market_data_ts,
        data_sources=data_sources,
        freshness_status=compute_freshness_status(latest_market_data_ts, now=now),
    )

    # Reference-period filter: only securities whose own latest bar IS the
    # global latest date go into movers/sector/breadth (see module docstring).
    as_of_rows = (
        [q for q in quotes if q.ts == latest_market_data_ts]
        if latest_market_data_ts is not None
        else []
    )
    valid: list[_RowWithReturn] = []
    for q in as_of_rows:
        return_percent = compute_return_percent(q.close, q.prev_close)
        if return_percent is not None:
            valid.append(_RowWithReturn(row=q, return_percent=return_percent))

    gainers = sorted(valid, key=lambda wr: (-wr.return_percent, wr.row.ticker))[:TOP_MOVERS_LIMIT]
    losers = sorted(valid, key=lambda wr: (wr.return_percent, wr.row.ticker))[:TOP_MOVERS_LIMIT]
    most_active = sorted(as_of_rows, key=lambda q: (-q.volume, q.ticker))[:TOP_MOVERS_LIMIT]

    market_movers = MarketMovers(
        as_of=latest_market_data_ts,
        top_gainers=[
            MoverItem(
                ticker=wr.row.ticker,
                name=wr.row.name,
                sector=wr.row.sector,
                last_price=wr.row.close,
                change_percent=wr.return_percent,
                volume=wr.row.volume,
            )
            for wr in gainers
        ],
        top_losers=[
            MoverItem(
                ticker=wr.row.ticker,
                name=wr.row.name,
                sector=wr.row.sector,
                last_price=wr.row.close,
                change_percent=wr.return_percent,
                volume=wr.row.volume,
            )
            for wr in losers
        ],
        most_active=[
            ActiveItem(
                ticker=q.ticker, name=q.name, sector=q.sector, last_price=q.close, volume=q.volume
            )
            for q in most_active
        ],
    )

    advancing = sum(1 for wr in valid if wr.return_percent > 0)
    declining = sum(1 for wr in valid if wr.return_percent < 0)
    unchanged = sum(1 for wr in valid if wr.return_percent == 0)
    market_breadth = MarketBreadth(
        as_of=latest_market_data_ts,
        status="ok" if as_of_rows else "unavailable",
        advancing=advancing if as_of_rows else None,
        declining=declining if as_of_rows else None,
        unchanged=unchanged if as_of_rows else None,
        no_data=total_securities - len(valid),
    )

    returns_by_sector: dict[str, list[Decimal]] = {}
    for wr in valid:
        returns_by_sector.setdefault(wr.row.sector or "Unknown", []).append(wr.return_percent)
    with_data_count_by_sector: dict[str, int] = {}
    for q in as_of_rows:
        key = q.sector or "Unknown"
        with_data_count_by_sector[key] = with_data_count_by_sector.get(key, 0) + 1

    sectors = [
        SectorPerformance(
            sector=sector,
            security_count=count,
            securities_with_data=with_data_count_by_sector.get(sector, 0),
            average_return_percent=(
                sum(returns_by_sector[sector], start=Decimal(0)) / len(returns_by_sector[sector])
                if returns_by_sector.get(sector)
                else None
            ),
        )
        for sector, count in sorted(sector_counts.items())
    ]
    sector_overview = SectorOverview(as_of=latest_market_data_ts, sectors=sectors)

    # Most-recently-updated securities across the WHOLE universe (not just
    # as_of_rows) — this section is "what changed recently", not
    # reference-date-bound like movers/breadth/sectors.
    recent_sorted = sorted(quotes, key=lambda q: q.ticker)
    recent_sorted = sorted(recent_sorted, key=lambda q: q.ts, reverse=True)
    recent_activity = [
        RecentActivityItem(ticker=q.ticker, name=q.name, last_price=q.close, as_of=q.ts)
        for q in recent_sorted[:RECENT_ACTIVITY_LIMIT]
    ]

    return DashboardOverview(
        market_summary=market_summary,
        market_movers=market_movers,
        sector_overview=sector_overview,
        market_breadth=market_breadth,
        recent_activity=recent_activity,
    )
