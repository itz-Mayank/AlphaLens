"""Market-data domain logic: ingestion orchestration and quote computation.

`run_ingestion` is the actual ingestion logic. It is called directly by
tests (no Celery involved) and from the Celery task
(`app/workers/tasks/market_data.py`) as a thin wrapper. This module never
imports Celery or FastAPI, so it stays testable and reusable on its own —
see docs/decisions.md ADR-001's rule extended to this service.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models.price_bar import PriceBar
from app.db.models.security import Security
from app.providers.base import MarketDataProvider, SecurityInfo
from app.providers.market_data import get_market_data_provider
from app.providers.market_data.universe import KNOWN_SECURITIES
from app.repositories.job_repository import JobRepository
from app.repositories.price_bar_repository import LatestQuoteRow, PriceBarRepository
from app.repositories.security_repository import SecurityRepository
from app.services.market_data_validation import detect_gaps, detect_price_warnings, validate_bars

logger = get_logger(__name__)

DEFAULT_LOOKBACK_DAYS = 730
WEEK_52_LOOKBACK_DAYS = 365
# Comfortably exceeds `ml.inference.serving.MIN_HISTORY_ROWS` (60) trading
# days even across weekends/holidays, while keeping the query bounded
# rather than fetching a security's entire history for a computation that
# only ever needs the trailing window.
OHLCV_DATAFRAME_LOOKBACK_DAYS = 200


def fetch_ohlcv_dataframe(
    db: Session, security: Security, *, lookback_days: int = OHLCV_DATAFRAME_LOOKBACK_DAYS
) -> pd.DataFrame:
    """`security`'s trailing price history as the `ticker, ts, open, high,
    low, close, volume` DataFrame `ml.features.pipeline.build_features`/
    `ml.inference.serving` expect. The one shared helper for this
    conversion — `forecast_service.py` and `app/agent/tools.py`'s
    technical-indicators tool both call this rather than each re-deriving
    it from `PriceBarRepository` rows independently.
    """
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    bars = PriceBarRepository(db).get_range(security_id=security.id, start=cutoff, end=None)
    return pd.DataFrame(
        [
            {
                "ticker": security.ticker,
                "ts": bar.ts.date(),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
            for bar in bars
        ]
    )


def run_ingestion(
    db: Session,
    *,
    job_id: uuid.UUID,
    tickers: list[str] | None,
    start_date: date | None,
    end_date: date | None,
    provider: MarketDataProvider | None = None,
) -> None:
    provider = provider or get_market_data_provider()
    jobs = JobRepository(db)
    securities = SecurityRepository(db)
    price_bars = PriceBarRepository(db)

    job = jobs.get_by_id(job_id)
    if job is None:
        logger.error("ingestion_job_not_found", job_id=str(job_id))
        return

    jobs.mark_running(job)
    db.flush()

    resolved_end = end_date or datetime.now(UTC).date()
    resolved_start = start_date or (resolved_end - timedelta(days=DEFAULT_LOOKBACK_DAYS))

    # Not every provider can enumerate "the securities it knows about" — a
    # real vendor like Twelve Data covers tens of thousands of instruments
    # and deliberately raises NotImplementedError from list_securities()
    # rather than return one (see its docstring). `metadata_by_ticker`
    # falls back to AlphaLens's own curated company list for name/sector/
    # exchange in that case, so "ingest my tracked tickers with real
    # prices" still has a concrete meaning even against a provider with no
    # universe of its own. A provider's own metadata (when available) wins
    # over the fallback, since it's the more authoritative source.
    try:
        provider_universe: dict[str, SecurityInfo] = {
            s.ticker: s for s in provider.list_securities()
        }
    except NotImplementedError:
        provider_universe = {}

    metadata_by_ticker: dict[str, SecurityInfo] = {s.ticker: s for s in KNOWN_SECURITIES}
    metadata_by_ticker.update(provider_universe)

    if tickers:
        target_tickers = [t.upper() for t in tickers]
    elif provider_universe:
        target_tickers = list(provider_universe.keys())
    else:
        target_tickers = list(metadata_by_ticker.keys())

    per_ticker_stats: dict[str, dict] = {}
    unknown_tickers: list[str] = []

    try:
        for ticker in target_tickers:
            info = metadata_by_ticker.get(ticker)
            if info is None:
                # A genuinely new ticker — neither the provider's own
                # universe nor AlphaLens's curated list knows it. Try one
                # last live discovery lookup (e.g. Twelve Data's real
                # symbol_search) before giving up, so ingesting a ticker
                # nobody has ever tracked before ("AMD", say) works without
                # first having to add it anywhere by hand.
                try:
                    discovered = provider.search_securities(ticker, limit=5)
                except NotImplementedError:
                    discovered = []
                info = next((m for m in discovered if m.ticker == ticker), None)
            if info is None:
                unknown_tickers.append(ticker)
                continue

            security = securities.get_or_create(
                ticker=info.ticker,
                name=info.name,
                exchange=info.exchange,
                sector=info.sector,
                industry=info.industry,
                currency=info.currency,
                data_source=provider.data_source,
            )

            raw_bars = provider.get_daily_bars(ticker, resolved_start, resolved_end)
            valid_bars, issues = validate_bars(raw_bars)
            gaps = detect_gaps(valid_bars)
            # WARNING-tier only — informational, never removes anything
            # from valid_bars (see market_data_validation.py's docstring
            # on why an abnormal move is flagged, not rejected).
            price_warnings = detect_price_warnings(valid_bars)
            written = price_bars.upsert_many(security_id=security.id, bars=valid_bars)

            per_ticker_stats[ticker] = {
                "bars_fetched": len(raw_bars),
                "bars_written": written,
                "bars_rejected": len(issues),
                "rejection_reasons": sorted({issue.reason for issue in issues}),
                "gap_count": len(gaps),
                "price_warning_count": len(price_warnings),
            }

        jobs.mark_completed(
            job,
            metadata={
                "tickers": target_tickers,
                "unknown_tickers": unknown_tickers,
                "start_date": resolved_start.isoformat(),
                "end_date": resolved_end.isoformat(),
                "per_ticker": per_ticker_stats,
            },
        )
    except Exception as exc:  # noqa: BLE001 — a job must record failure, never raise to the caller
        logger.error("ingestion_failed", job_id=str(job_id), error=str(exc))
        jobs.mark_failed(job, error=str(exc))

    db.flush()


@dataclass(frozen=True)
class Quote:
    last_price: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None
    volume: int | None
    as_of: datetime | None


def compute_price_change(
    close: Decimal, prev_close: Decimal | None
) -> tuple[Decimal | None, Decimal | None]:
    """`(change, change_percent)`. `None` when there's no previous close to
    compare against, or it's zero (a percent change against zero is
    undefined, not infinite or zero — never fabricate a number there).

    The single canonical formula for "percent change" in the codebase —
    `dashboard_service.compute_return_percent` calls this too. Two
    formulas that are algebraically equivalent
    (`(close/prev - 1) * 100` vs `((close - prev) / prev) * 100`) can
    still disagree in their last few digits under fixed-precision Decimal
    arithmetic, which a real cross-check between `/stocks/{ticker}` and
    `/dashboard/overview` caught for the same security on the same day —
    they must use the exact same code path, not just the same math.
    """
    if prev_close is None or prev_close == 0:
        return None, None
    change = close - prev_close
    change_percent = (change / prev_close) * Decimal(100)
    return change, change_percent


def compute_quote(price_bars: list[PriceBar]) -> Quote:
    """`price_bars` must be the two most recent bars, most-recent first."""
    if not price_bars:
        return Quote(None, None, None, None, None)

    latest = price_bars[0]
    previous = price_bars[1] if len(price_bars) > 1 else None
    change, change_percent = compute_price_change(
        latest.close, previous.close if previous is not None else None
    )

    return Quote(
        last_price=latest.close,
        change=change,
        change_percent=change_percent,
        volume=latest.volume,
        as_of=latest.ts,
    )


def quote_from_latest_row(row: LatestQuoteRow) -> Quote:
    """Same computation as `compute_quote`, from a batched
    `PriceBarRepository.get_latest_quotes()` row instead of two `PriceBar`
    objects — used wherever quotes are needed for many securities at once
    (stock list, dashboard) to avoid one query per security."""
    change, change_percent = compute_price_change(row.close, row.prev_close)
    return Quote(
        last_price=row.close,
        change=change,
        change_percent=change_percent,
        volume=row.volume,
        as_of=row.ts,
    )


def compute_52_week_range(
    price_bar_repo: PriceBarRepository, *, security_id: int, as_of: datetime
) -> tuple[Decimal | None, Decimal | None]:
    start = as_of - timedelta(days=WEEK_52_LOOKBACK_DAYS)
    bars = price_bar_repo.get_range(security_id=security_id, start=start, end=as_of)
    if not bars:
        return None, None
    return max(bar.high for bar in bars), min(bar.low for bar in bars)
