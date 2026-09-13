"""Real-data stock screener: filters/sorts/paginates over securities using
only data this deployment actually has. No hardcoded/fabricated values —
every field traces back to `price_bars`, the registered ML models, or
scored news sentiment, and is `None` (never a fabricated zero) when that
data isn't available for a given security.

Batched by construction: one query for the candidate universe
(`SecurityRepository.list_matching`), one for latest quotes
(`PriceBarRepository.get_latest_quotes`), one for multi-security OHLCV
history (`PriceBarRepository.get_bars_for_securities`) — regardless of how
many securities are in scope. Forecasts reuse the models loaded once by
`ml_common.load_models()` and are computed from the ALREADY-fetched OHLCV
slice via the same `ml.inference.serving.build_latest_feature_row` feature
pipeline `forecast_service` uses for a single ticker — zero additional DB
queries per security.

Sentiment is the one exception: `news_query_service.get_sentiment_overview`
runs its own query pair per candidate security (aggregation isn't batched
across securities today — see `news_sentiment_aggregation.py`). This is a
documented, bounded Phase 9 scope decision appropriate for a small demo
security universe, not an oversight (see docs/decisions.md's Phase 9 ADR).
A screener over a much larger universe would need a batched sentiment
aggregation query, which is out of scope here.

Pagination is deterministic: the candidate universe is fetched in a fixed
`ticker ASC` order and Python's sort is stable, so filtering/sorting by any
field always breaks ties by ticker — the same filters+sort always return
the same page for the same underlying data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
from ml.features.pipeline import FEATURE_COLUMNS
from ml.inference import serving
from ml.inference.inference import predict_direction
from ml.targets.targets import CLASS_NAMES
from sqlalchemy.orm import Session

from app.db.models.price_bar import PriceBar
from app.repositories.price_bar_repository import PriceBarRepository
from app.repositories.security_repository import SecurityRepository
from app.services import ml_common, news_query_service
from app.services.market_data_service import Quote, quote_from_latest_row

# Matches market_data_service.OHLCV_DATAFRAME_LOOKBACK_DAYS — comfortably
# exceeds serving.MIN_HISTORY_ROWS even across weekends/holidays.
SCREENER_HISTORY_DAYS = 200
RETURN_WINDOW_DAYS = 20


@dataclass(frozen=True)
class ScreenerFilters:
    query: str | None = None
    sector: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    min_change_percent: Decimal | None = None
    max_change_percent: Decimal | None = None
    min_return_20d_percent: float | None = None
    max_return_20d_percent: float | None = None
    forecast_direction: str | None = None  # one of ml.targets.targets.CLASS_NAMES
    min_sentiment_score: float | None = None
    sort_by: str = "ticker"
    sort_direction: str = "asc"
    limit: int = 25
    offset: int = 0


@dataclass(frozen=True)
class ScreenerRow:
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
    unavailable_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScreenerResult:
    items: list[ScreenerRow]
    total: int
    limit: int
    offset: int
    forecast_available: bool
    forecast_unavailable_reason: str | None


_SORT_KEYS = {
    "ticker": lambda r: r.ticker,
    "last_price": lambda r: (r.last_price is None, r.last_price),
    "change_percent": lambda r: (r.change_percent is None, r.change_percent),
    "return_20d_percent": lambda r: (r.return_20d_percent is None, r.return_20d_percent),
    "volume": lambda r: (r.volume is None, r.volume),
    "rsi_14": lambda r: (r.rsi_14 is None, r.rsi_14),
    "sentiment_score": lambda r: (r.sentiment_score is None, r.sentiment_score),
}


def _ohlcv_frame(ticker: str, bars: list[PriceBar]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
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


def run_screener(db: Session, filters: ScreenerFilters) -> ScreenerResult:
    # Sector/ticker-substring filters happen in SQL; everything derived
    # (returns, indicators, forecast, sentiment) is not a SQL column and is
    # necessarily computed in memory before it can be filtered/sorted on.
    candidates = SecurityRepository(db).list_matching(query=filters.query, sector=filters.sector)
    if not candidates:
        return ScreenerResult(
            items=[], total=0, limit=filters.limit, offset=filters.offset,
            forecast_available=False, forecast_unavailable_reason=None,
        )

    security_ids = [s.id for s in candidates]
    quotes_by_id = {
        row.security_id: quote_from_latest_row(row)
        for row in PriceBarRepository(db).get_latest_quotes(security_ids=security_ids)
    }

    cutoff = datetime.now(UTC) - timedelta(days=SCREENER_HISTORY_DAYS)
    bars_by_id: dict[int, list[PriceBar]] = {}
    for bar in PriceBarRepository(db).get_bars_for_securities(
        security_ids=security_ids, start=cutoff
    ):
        bars_by_id.setdefault(bar.security_id, []).append(bar)

    models = None
    forecast_unavailable_reason: str | None = None
    try:
        models = ml_common.load_models()
    except serving.ServingError as exc:
        forecast_unavailable_reason = str(exc)

    rows: list[ScreenerRow] = []
    for security in candidates:
        unavailable: list[str] = []
        quote: Quote = quotes_by_id.get(security.id, Quote(None, None, None, None, None))
        if quote.as_of is None:
            unavailable.append("last_price")

        security_bars = sorted(bars_by_id.get(security.id, []), key=lambda b: b.ts)

        return_20d_percent: float | None = None
        if len(security_bars) >= RETURN_WINDOW_DAYS + 1:
            closes = [float(b.close) for b in security_bars]
            start_price = closes[-(RETURN_WINDOW_DAYS + 1)]
            if start_price:
                return_20d_percent = (closes[-1] / start_price - 1) * 100
        if return_20d_percent is None:
            unavailable.append("return_20d_percent")

        rsi_14: float | None = None
        forecast_direction: str | None = None
        if models is not None and security.ticker in models.supported_tickers:
            frame = _ohlcv_frame(security.ticker, security_bars)
            try:
                feature_row = serving.build_latest_feature_row(frame)
            except serving.ServingError:
                feature_row = None
            if feature_row is not None:
                rsi_14 = float(feature_row["rsi_14"])
                X = pd.DataFrame([feature_row[list(FEATURE_COLUMNS)].to_dict()])
                prediction = predict_direction(
                    models.direction_model,
                    X,
                    ticker=security.ticker,
                    as_of=feature_row["ts"],
                    model_name=models.direction_record["model_name"],
                    model_version=models.direction_record["version"],
                    feature_set_version=models.direction_record["feature_version"],
                    class_names=CLASS_NAMES,
                )
                forecast_direction = prediction.predicted_class
        if rsi_14 is None:
            unavailable.append("rsi_14")
        if forecast_direction is None:
            unavailable.append("forecast_direction")

        sentiment_score: float | None = None
        sentiment_overview = news_query_service.get_sentiment_overview(db, security=security)
        sentiment_score = sentiment_overview["last_7d"]["average_sentiment_score"]
        if sentiment_score is None:
            unavailable.append("sentiment_score")

        rows.append(
            ScreenerRow(
                security_id=security.id,
                ticker=security.ticker,
                name=security.name,
                sector=security.sector,
                last_price=quote.last_price,
                change_percent=quote.change_percent,
                volume=quote.volume,
                return_20d_percent=return_20d_percent,
                rsi_14=rsi_14,
                forecast_direction=forecast_direction,
                sentiment_score=sentiment_score,
                unavailable_fields=unavailable,
            )
        )

    filtered = _apply_filters(rows, filters)

    sort_key = _SORT_KEYS.get(filters.sort_by, _SORT_KEYS["ticker"])
    filtered.sort(key=sort_key, reverse=(filters.sort_direction == "desc"))

    total = len(filtered)
    page = filtered[filters.offset : filters.offset + filters.limit]

    return ScreenerResult(
        items=page,
        total=total,
        limit=filters.limit,
        offset=filters.offset,
        forecast_available=models is not None,
        forecast_unavailable_reason=forecast_unavailable_reason,
    )


def _apply_filters(rows: list[ScreenerRow], filters: ScreenerFilters) -> list[ScreenerRow]:
    result = rows
    if filters.min_price is not None:
        result = [
            r for r in result if r.last_price is not None and r.last_price >= filters.min_price
        ]
    if filters.max_price is not None:
        result = [
            r for r in result if r.last_price is not None and r.last_price <= filters.max_price
        ]
    if filters.min_change_percent is not None:
        result = [
            r for r in result
            if r.change_percent is not None and r.change_percent >= filters.min_change_percent
        ]
    if filters.max_change_percent is not None:
        result = [
            r for r in result
            if r.change_percent is not None and r.change_percent <= filters.max_change_percent
        ]
    if filters.min_return_20d_percent is not None:
        result = [
            r for r in result
            if r.return_20d_percent is not None
            and r.return_20d_percent >= filters.min_return_20d_percent
        ]
    if filters.max_return_20d_percent is not None:
        result = [
            r for r in result
            if r.return_20d_percent is not None
            and r.return_20d_percent <= filters.max_return_20d_percent
        ]
    if filters.forecast_direction is not None:
        result = [r for r in result if r.forecast_direction == filters.forecast_direction]
    if filters.min_sentiment_score is not None:
        result = [
            r for r in result
            if r.sentiment_score is not None and r.sentiment_score >= filters.min_sentiment_score
        ]
    return result
