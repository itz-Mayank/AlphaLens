"""The agent's controlled tool system.

Every tool wraps an EXISTING service/repository — nothing here duplicates
database logic, computes a financial metric, or trains anything. The LLM
selects a tool and supplies validated arguments; this module executes
deterministic application code and returns structured data plus
`Evidence`. There is no `execute_sql`/`execute_python`/`execute_shell`/
filesystem tool, and there never will be — that boundary is a security
property of this module's contents, not an oversight (see
docs/decisions.md's tool-boundary ADR and docs/security.md).

A tool never raises past its own boundary: any failure (unknown ticker,
insufficient history, unavailable model, provider error) becomes a
`{"error": "..."}` output with no evidence, which the LLM can see and
explain honestly to the user — never a stack trace, never a fabricated
substitute result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ml.inference.serving import (
    DataValidationFailedError,
    InsufficientHistoryError,
    build_latest_feature_row,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models.security import Security
from app.db.models.user import User
from app.repositories.alert_repository import AlertRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.price_bar_repository import PriceBarRepository
from app.repositories.security_repository import SecurityRepository
from app.repositories.watchlist_repository import WatchlistRepository
from app.services import (
    backtest_service,
    forecast_service,
    fundamentals_service,
    macro_service,
    news_query_service,
    portfolio_service,
    provider_health_service,
)
from app.services.market_data_service import compute_quote, fetch_ohlcv_dataframe
from app.services.screener_service import ScreenerFilters, run_screener
from app.services.watchlist_service import get_watchlist_detail

from .evidence import Evidence, EvidenceSourceType
from .llm_provider import ToolDefinition

MAX_BACKTEST_TICKERS = 5
_INDICATOR_COLUMNS = (
    "sma_20",
    "ema_12",
    "rsi_14",
    "macd_line",
    "macd_signal",
    "macd_histogram",
    "volatility_20d",
    "atr_14",
    "bollinger_percent_b",
    "relative_volume_20",
)


def _coerce_to_datetime(value: Any) -> datetime:
    """Service-layer dicts mix raw `datetime`/`date` objects (forecast,
    news) with pre-`.isoformat()`'d strings (sentiment aggregation) —
    handles both so every `Evidence.timestamp` is a real `datetime`,
    never a string."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise TypeError(f"Cannot coerce {type(value).__name__} to datetime")


def _resolve_security(db: Session, ticker: str) -> Security | None:
    return SecurityRepository(db).get_by_ticker(ticker.upper())


@dataclass(frozen=True)
class ToolResult:
    output: dict[str, Any]
    evidence: list[Evidence]


def _unknown_ticker_result(ticker: str) -> ToolResult:
    return ToolResult(
        output={"error": f"Unknown ticker '{ticker.upper()}' — not tracked by this deployment."},
        evidence=[],
    )


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    # Each concrete handler narrows the third parameter to its own
    # `input_model` subtype (e.g. `TickerInput`) — `Any` here is the
    # correct escape hatch for that per-tool contravariance, not laziness.
    handler: Callable[[Session, User, Any], ToolResult]

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
        )


# --- Input schemas -----------------------------------------------------


class TickerInput(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol, e.g. AAPL", max_length=10)


class PriceHistoryInput(BaseModel):
    ticker: str = Field(..., max_length=10)
    days: int = Field(default=30, ge=1, le=365, description="Trailing window in days")


class ForecastExplanationInput(BaseModel):
    ticker: str = Field(..., max_length=10)
    top_n: int = Field(default=5, ge=1, le=10, description="Number of top contributing factors")


class NewsInput(BaseModel):
    ticker: str = Field(..., max_length=10)
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of articles")


class SentimentHistoryInput(BaseModel):
    ticker: str = Field(..., max_length=10)
    days: int = Field(default=14, ge=1, le=90)


class BacktestInput(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=MAX_BACKTEST_TICKERS)
    start_date: date
    end_date: date
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)


class EmptyInput(BaseModel):
    """No arguments — the tool always scopes to the current authenticated
    user, never a caller-supplied id (see this module's docstring)."""


class WatchlistNameInput(BaseModel):
    name: str = Field(..., max_length=200, description="The watchlist's name, as the user named it")


class ScreenerToolInput(BaseModel):
    sector: str | None = Field(default=None)
    forecast_direction: str | None = Field(
        default=None, description="Bearish, Neutral, or Bullish"
    )
    min_sentiment_score: float | None = Field(default=None, ge=-1, le=1)
    sort_by: str = Field(default="ticker")
    sort_direction: str = Field(default="asc", pattern="^(asc|desc)$")
    limit: int = Field(default=10, ge=1, le=25)


class PortfolioNameInput(BaseModel):
    name: str = Field(..., max_length=200, description="The portfolio's name, as the user named it")


class MacroSeriesInput(BaseModel):
    series_id: str = Field(
        ...,
        max_length=50,
        description=(
            "A macro series id this deployment tracks, e.g. FEDFUNDS, CPIAUCSL, UNRATE, GDP, "
            "DGS10. An id outside this small tracked set simply reports as unavailable, never "
            "a fabricated value."
        ),
    )


# --- Tool handlers -------------------------------------------------------


def _get_stock_quote(db: Session, _user: User, args: TickerInput) -> ToolResult:
    security = _resolve_security(db, args.ticker)
    if security is None:
        return _unknown_ticker_result(args.ticker)
    bars = PriceBarRepository(db).get_latest(security_id=security.id, limit=2)
    quote = compute_quote(bars)
    if quote.as_of is None:
        return ToolResult(
            output={"error": f"No price data is available yet for {security.ticker}."}, evidence=[]
        )
    data = {
        "ticker": security.ticker,
        "last_price": float(quote.last_price) if quote.last_price is not None else None,
        "change": float(quote.change) if quote.change is not None else None,
        "change_percent": float(quote.change_percent) if quote.change_percent is not None else None,
        "volume": quote.volume,
        "as_of": quote.as_of.isoformat(),
        "data_source": security.data_source,
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.MARKET_DATA,
            source_id=f"quote:{security.ticker}",
            ticker=security.ticker,
            timestamp=_coerce_to_datetime(quote.as_of),
            data=data,
            provenance=security.data_source,
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_price_history(db: Session, _user: User, args: PriceHistoryInput) -> ToolResult:
    security = _resolve_security(db, args.ticker)
    if security is None:
        return _unknown_ticker_result(args.ticker)
    start = datetime.now(UTC) - timedelta(days=args.days)
    bars = PriceBarRepository(db).get_range(security_id=security.id, start=start, end=None)
    if not bars:
        return ToolResult(
            output={
                "error": (
                    f"No price history is available for {security.ticker} "
                    f"in the last {args.days} days."
                )
            },
            evidence=[],
        )
    closes = [float(b.close) for b in bars]
    start_price, end_price = closes[0], closes[-1]
    data = {
        "ticker": security.ticker,
        "days": args.days,
        "num_bars": len(bars),
        "start_date": bars[0].ts.date().isoformat(),
        "end_date": bars[-1].ts.date().isoformat(),
        "start_price": start_price,
        "end_price": end_price,
        "high": max(float(b.high) for b in bars),
        "low": min(float(b.low) for b in bars),
        "cumulative_return_percent": (end_price / start_price - 1) * 100 if start_price else None,
        "data_source": security.data_source,
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.MARKET_DATA,
            source_id=f"price_history:{security.ticker}:{args.days}d",
            ticker=security.ticker,
            timestamp=_coerce_to_datetime(bars[-1].ts),
            data=data,
            provenance=security.data_source,
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_technical_indicators(db: Session, _user: User, args: TickerInput) -> ToolResult:
    security = _resolve_security(db, args.ticker)
    if security is None:
        return _unknown_ticker_result(args.ticker)
    history = fetch_ohlcv_dataframe(db, security)
    try:
        feature_row = build_latest_feature_row(history)
    except (InsufficientHistoryError, DataValidationFailedError) as exc:
        return ToolResult(output={"error": str(exc)}, evidence=[])

    indicators = {col: float(feature_row[col]) for col in _INDICATOR_COLUMNS}
    data = {
        "ticker": security.ticker,
        "as_of": str(feature_row["ts"]),
        "indicators": indicators,
        "data_source": security.data_source,
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.MARKET_DATA,
            source_id=f"indicators:{security.ticker}",
            ticker=security.ticker,
            timestamp=_coerce_to_datetime(feature_row["ts"]),
            data=data,
            provenance=security.data_source,
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_forecast(db: Session, _user: User, args: TickerInput) -> ToolResult:
    try:
        result = forecast_service.get_forecast(db, args.ticker.upper())
    except AppError as exc:
        return ToolResult(output={"error": exc.message}, evidence=[])
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.FORECAST,
            source_id=f"forecast:{result['ticker']}",
            ticker=result["ticker"],
            timestamp=_coerce_to_datetime(result["prediction_timestamp"]),
            data=result,
            provenance=result["return_model_version"],
        )
    ]
    return ToolResult(output=result, evidence=evidence)


def _get_forecast_explanation(
    db: Session, _user: User, args: ForecastExplanationInput
) -> ToolResult:
    try:
        result = forecast_service.get_forecast_explanation(
            db, args.ticker.upper(), top_n=args.top_n
        )
    except AppError as exc:
        return ToolResult(output={"error": exc.message}, evidence=[])
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.SHAP,
            source_id=f"shap:{result['ticker']}",
            ticker=result["ticker"],
            timestamp=_coerce_to_datetime(result["as_of"]),
            data=result,
            provenance=result["model_version"],
        )
    ]
    return ToolResult(output=result, evidence=evidence)


def _get_news(db: Session, _user: User, args: NewsInput) -> ToolResult:
    security = _resolve_security(db, args.ticker)
    if security is None:
        return _unknown_ticker_result(args.ticker)
    result = news_query_service.get_recent_news(db, security=security, limit=args.limit)
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.NEWS,
            source_id=f"article:{article['id']}",
            ticker=security.ticker,
            timestamp=_coerce_to_datetime(article["published_at"]),
            data=article,
            provenance=article["url"],
        )
        for article in result["articles"]
    ]
    return ToolResult(output=result, evidence=evidence)


def _get_sentiment(db: Session, _user: User, args: TickerInput) -> ToolResult:
    security = _resolve_security(db, args.ticker)
    if security is None:
        return _unknown_ticker_result(args.ticker)
    result = news_query_service.get_sentiment_overview(db, security=security)
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.SENTIMENT,
            source_id=f"sentiment:{security.ticker}",
            ticker=security.ticker,
            timestamp=_coerce_to_datetime(result["last_7d"]["as_of"]),
            data=result,
            provenance=result["model_version"],
        )
    ]
    return ToolResult(output=result, evidence=evidence)


def _get_sentiment_history(db: Session, _user: User, args: SentimentHistoryInput) -> ToolResult:
    security = _resolve_security(db, args.ticker)
    if security is None:
        return _unknown_ticker_result(args.ticker)
    result = news_query_service.get_sentiment_history(db, security=security, days=args.days)
    latest = result["points"][-1]["date"] if result["points"] else datetime.now(UTC).date()
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.SENTIMENT,
            source_id=f"sentiment_history:{security.ticker}:{args.days}d",
            ticker=security.ticker,
            timestamp=_coerce_to_datetime(latest),
            data=result,
            provenance=result["model_version"],
        )
    ]
    return ToolResult(output=result, evidence=evidence)


def _run_backtest(db: Session, _user: User, args: BacktestInput) -> ToolResult:
    try:
        result = backtest_service.run_backtest(
            db,
            tickers=[t.upper() for t in args.tickers],
            start_date=args.start_date,
            end_date=args.end_date,
            commission_bps=args.commission_bps,
            slippage_bps=args.slippage_bps,
            initial_capital=100_000.0,
            max_position_weight=None,
        )
    except AppError as exc:
        return ToolResult(output={"error": exc.message}, evidence=[])

    # Controlled context (Step 14): the LLM gets metrics + a point count,
    # never the full daily equity curve array.
    summary = {k: v for k, v in result.items() if k != "equity_curve"}
    summary["equity_curve_points"] = len(result["equity_curve"])
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.BACKTEST,
            source_id=f"backtest:{','.join(result['tickers'])}:{args.start_date}:{args.end_date}",
            ticker=None,
            timestamp=datetime.now(UTC),
            data=summary,
            provenance=result["model_version"],
        )
    ]
    return ToolResult(output=summary, evidence=evidence)


def _find_watchlist_by_name(db: Session, user: User, name: str):  # noqa: ANN201 - Watchlist ORM row
    for watchlist in WatchlistRepository(db).list_for_user(user_id=user.id):
        if watchlist.name.strip().lower() == name.strip().lower():
            return watchlist
    return None


def _find_portfolio_by_name(db: Session, user: User, name: str):  # noqa: ANN201 - Portfolio ORM row
    for portfolio in PortfolioRepository(db).list_for_user(user_id=user.id):
        if portfolio.name.strip().lower() == name.strip().lower():
            return portfolio
    return None


def _get_watchlists(db: Session, user: User, _args: EmptyInput) -> ToolResult:
    repo = WatchlistRepository(db)
    watchlists = repo.list_for_user(user_id=user.id)
    data = {
        "watchlists": [
            {
                "name": w.name,
                "description": w.description,
                "item_count": repo.count_items(watchlist_id=w.id),
            }
            for w in watchlists
        ]
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.WATCHLIST,
            source_id=f"watchlists:{user.id}",
            ticker=None,
            timestamp=datetime.now(UTC),
            data=data,
            provenance="watchlist_service",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_watchlist(db: Session, user: User, args: WatchlistNameInput) -> ToolResult:
    watchlist = _find_watchlist_by_name(db, user, args.name)
    if watchlist is None:
        return ToolResult(
            output={"error": f"No watchlist named '{args.name}' was found."}, evidence=[]
        )
    detail = get_watchlist_detail(db, watchlist)
    data = {
        "name": watchlist.name,
        "description": watchlist.description,
        "items": [
            {
                "ticker": item.ticker,
                "name": item.name,
                "last_price": float(item.last_price) if item.last_price is not None else None,
                "change_percent": (
                    float(item.change_percent) if item.change_percent is not None else None
                ),
                "data_unavailable": item.data_unavailable,
            }
            for item in detail.items
        ],
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.WATCHLIST,
            source_id=f"watchlist:{watchlist.id}",
            ticker=None,
            timestamp=datetime.now(UTC),
            data=data,
            provenance="watchlist_service",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _run_screener_tool(db: Session, _user: User, args: ScreenerToolInput) -> ToolResult:
    filters = ScreenerFilters(
        sector=args.sector,
        forecast_direction=args.forecast_direction,
        min_sentiment_score=args.min_sentiment_score,
        sort_by=args.sort_by,
        sort_direction=args.sort_direction,
        limit=args.limit,
        offset=0,
    )
    result = run_screener(db, filters)
    data = {
        "total_matches": result.total,
        "forecast_available": result.forecast_available,
        "items": [
            {
                "ticker": r.ticker,
                "name": r.name,
                "sector": r.sector,
                "last_price": float(r.last_price) if r.last_price is not None else None,
                "change_percent": (
                    float(r.change_percent) if r.change_percent is not None else None
                ),
                "return_20d_percent": r.return_20d_percent,
                "forecast_direction": r.forecast_direction,
                "sentiment_score": r.sentiment_score,
                "unavailable_fields": r.unavailable_fields,
            }
            for r in result.items
        ],
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.SCREENER,
            source_id=f"screener:{datetime.now(UTC).isoformat()}",
            ticker=None,
            timestamp=datetime.now(UTC),
            data=data,
            provenance="screener_service",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_portfolio(db: Session, user: User, args: PortfolioNameInput) -> ToolResult:
    portfolio = _find_portfolio_by_name(db, user, args.name)
    if portfolio is None:
        return ToolResult(
            output={"error": f"No portfolio named '{args.name}' was found."}, evidence=[]
        )
    data = {
        "name": portfolio.name,
        "description": portfolio.description,
        "base_currency": portfolio.base_currency,
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.PORTFOLIO,
            source_id=f"portfolio:{portfolio.id}",
            ticker=None,
            timestamp=datetime.now(UTC),
            data=data,
            provenance="portfolio_service",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_portfolio_holdings(db: Session, user: User, args: PortfolioNameInput) -> ToolResult:
    portfolio = _find_portfolio_by_name(db, user, args.name)
    if portfolio is None:
        return ToolResult(
            output={"error": f"No portfolio named '{args.name}' was found."}, evidence=[]
        )
    holdings = portfolio_service.get_holdings(db, portfolio)
    data = {
        "portfolio_name": portfolio.name,
        "holdings": [
            {
                "ticker": h.ticker,
                "quantity": float(h.quantity),
                "average_cost": float(h.average_cost),
                "last_price": float(h.last_price) if h.last_price is not None else None,
                "market_value": float(h.market_value) if h.market_value is not None else None,
                "unrealized_pnl": (
                    float(h.unrealized_pnl) if h.unrealized_pnl is not None else None
                ),
            }
            for h in holdings
        ],
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.PORTFOLIO,
            source_id=f"portfolio_holdings:{portfolio.id}",
            ticker=None,
            timestamp=datetime.now(UTC),
            data=data,
            provenance="portfolio_service",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_portfolio_performance(db: Session, user: User, args: PortfolioNameInput) -> ToolResult:
    """Never computes returns/P&L itself — it reports exactly what
    `portfolio_service.get_analytics`/`get_performance_history` (the
    application's own deterministic accounting engine) already computed.
    The LLM explains these numbers; it never derives them (see this
    module's docstring)."""
    portfolio = _find_portfolio_by_name(db, user, args.name)
    if portfolio is None:
        return ToolResult(
            output={"error": f"No portfolio named '{args.name}' was found."}, evidence=[]
        )
    analytics = portfolio_service.get_analytics(db, portfolio)
    data = {
        "portfolio_name": portfolio.name,
        "cash": float(analytics.cash),
        "invested_capital": float(analytics.invested_capital),
        "market_value": (
            float(analytics.market_value) if analytics.market_value is not None else None
        ),
        "total_value": (
            float(analytics.total_value) if analytics.total_value is not None else None
        ),
        "realized_pnl": float(analytics.realized_pnl),
        "unrealized_pnl": (
            float(analytics.unrealized_pnl) if analytics.unrealized_pnl is not None else None
        ),
        "total_return_percent": (
            float(analytics.total_return_percent)
            if analytics.total_return_percent is not None
            else None
        ),
        "market_value_is_partial": analytics.market_value_is_partial,
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.PORTFOLIO,
            source_id=f"portfolio_performance:{portfolio.id}",
            ticker=None,
            timestamp=datetime.now(UTC),
            data=data,
            provenance="portfolio_service",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_alerts(db: Session, user: User, _args: EmptyInput) -> ToolResult:
    alerts = AlertRepository(db).list_for_user(user_id=user.id)
    securities_by_id = {
        s.id: s for s in SecurityRepository(db).get_by_ids([a.security_id for a in alerts])
    }
    data = {
        "alerts": [
            {
                "ticker": securities_by_id[a.security_id].ticker
                if a.security_id in securities_by_id
                else "UNKNOWN",
                "alert_type": a.alert_type,
                "config": a.config,
                "enabled": a.enabled,
                "last_triggered_at": (
                    a.last_triggered_at.isoformat() if a.last_triggered_at else None
                ),
            }
            for a in alerts
        ]
    }
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.ALERT,
            source_id=f"alerts:{user.id}",
            ticker=None,
            timestamp=datetime.now(UTC),
            data=data,
            provenance="alert_repository",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_fundamentals(db: Session, _user: User, args: TickerInput) -> ToolResult:
    report = fundamentals_service.get_fundamentals(db, ticker=args.ticker.upper())
    if report is None:
        return _unknown_ticker_result(args.ticker)
    data = {
        "ticker": report.ticker,
        "available": report.available,
        "reason": report.reason,
        "source": report.source,
        "retrieved_at": report.retrieved_at,
        "facts": [vars(f) for f in report.facts],
    }
    if not report.available:
        return ToolResult(output=data, evidence=[])
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.FUNDAMENTALS,
            source_id=f"fundamentals:{report.ticker}",
            ticker=report.ticker,
            timestamp=_coerce_to_datetime(report.retrieved_at),
            data=data,
            provenance=report.source or "unknown",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_macro_indicators(db: Session, _user: User, args: MacroSeriesInput) -> ToolResult:
    report = macro_service.get_macro_series(db, series_id=args.series_id.upper())
    data = {
        "series_id": report.series_id,
        "available": report.available,
        "reason": report.reason,
        "source": report.source,
        "observations": [vars(o) for o in report.observations],
    }
    if not report.available:
        return ToolResult(output=data, evidence=[])
    latest = report.observations[-1]
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.MACRO,
            source_id=f"macro:{report.series_id}",
            ticker=None,
            timestamp=_coerce_to_datetime(latest.observation_date),
            data=data,
            provenance=report.source or "unknown",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


def _get_data_source_status(db: Session, _user: User, _args: EmptyInput) -> ToolResult:
    statuses = provider_health_service.get_provider_statuses(db)
    data = {"providers": [vars(s) for s in statuses]}
    evidence = [
        Evidence(
            source_type=EvidenceSourceType.SYSTEM,
            source_id="provider_status",
            ticker=None,
            timestamp=datetime.now(UTC),
            data=data,
            provenance="provider_health_service",
        )
    ]
    return ToolResult(output=data, evidence=evidence)


TOOLS: list[Tool] = [
    Tool(
        "get_stock_quote",
        "Get the latest price quote (last price, change, volume) for a stock ticker.",
        TickerInput,
        _get_stock_quote,
    ),
    Tool(
        "get_price_history",
        "Get a summary of a stock's price history over a trailing window (start/end price, "
        "high/low, cumulative return) — not a raw daily bar dump.",
        PriceHistoryInput,
        _get_price_history,
    ),
    Tool(
        "get_technical_indicators",
        "Get the latest technical indicator values (SMA, EMA, RSI, MACD, volatility, ATR, "
        "Bollinger %B, relative volume) for a stock.",
        TickerInput,
        _get_technical_indicators,
    ),
    Tool(
        "get_forecast",
        "Get the current XGBoost 5-day return/direction forecast for a stock, with model "
        "version and data-source provenance.",
        TickerInput,
        _get_forecast,
    ),
    Tool(
        "get_forecast_explanation",
        "Get the top-N SHAP factors behind the current forecast for a stock — contribution, "
        "not causation.",
        ForecastExplanationInput,
        _get_forecast_explanation,
    ),
    Tool(
        "get_news",
        "Get recent news articles mapped to a stock, each with its FinBERT sentiment label if "
        "already scored.",
        NewsInput,
        _get_news,
    ),
    Tool(
        "get_sentiment",
        "Get the current 24-hour and 7-day aggregated news sentiment for a stock.",
        TickerInput,
        _get_sentiment,
    ),
    Tool(
        "get_sentiment_history",
        "Get daily aggregated sentiment history for a stock over a trailing window.",
        SentimentHistoryInput,
        _get_sentiment_history,
    ),
    Tool(
        "run_backtest",
        "Run the portfolio backtest engine over a date range for up to "
        f"{MAX_BACKTEST_TICKERS} tickers and return summary performance metrics.",
        BacktestInput,
        _run_backtest,
    ),
    Tool(
        "get_watchlists",
        "List the current user's own watchlists with their item counts. Takes no arguments — "
        "always scoped to the authenticated user, never another user's data.",
        EmptyInput,
        _get_watchlists,
    ),
    Tool(
        "get_watchlist",
        "Get one of the current user's own watchlists by name, including each item's latest "
        "quote.",
        WatchlistNameInput,
        _get_watchlist,
    ),
    Tool(
        "run_screener",
        "Screen tracked stocks by sector, forecast direction, and/or sentiment score using this "
        "deployment's own real data — never fabricated results. Fields the screener could not "
        "compute for a stock (e.g. insufficient price history) are null, not zero.",
        ScreenerToolInput,
        _run_screener_tool,
    ),
    Tool(
        "get_portfolio",
        "Get one of the current user's own portfolios by name (name, description, base "
        "currency only — use get_portfolio_holdings/get_portfolio_performance for figures).",
        PortfolioNameInput,
        _get_portfolio,
    ),
    Tool(
        "get_portfolio_holdings",
        "Get the current, application-computed holdings (quantity, average cost, market value, "
        "unrealized P&L) for one of the current user's own portfolios, by name.",
        PortfolioNameInput,
        _get_portfolio_holdings,
    ),
    Tool(
        "get_portfolio_performance",
        "Get the current, application-computed performance summary (cash, total value, "
        "realized/unrealized P&L, total return) for one of the current user's own portfolios, "
        "by name. These figures are always computed by the application's own accounting "
        "service, never by this tool or the model calling it.",
        PortfolioNameInput,
        _get_portfolio_performance,
    ),
    Tool(
        "get_alerts",
        "List the current user's own alerts (ticker, type, config, enabled state, last "
        "triggered time). Takes no arguments — always scoped to the authenticated user.",
        EmptyInput,
        _get_alerts,
    ),
    Tool(
        "get_fundamentals",
        "Get as-filed company fundamentals (e.g. Assets, Revenues, NetIncomeLoss) for a stock, "
        "sourced from SEC EDGAR filings with provenance (form, filing date, accession number). "
        "Never a derived ratio like P/E — reports `available: false` in Demo Mode or for any "
        "security with nothing ingested yet, never a fabricated value.",
        TickerInput,
        _get_fundamentals,
    ),
    Tool(
        "get_macro_indicators",
        "Get observations for a tracked macro-economic series (FEDFUNDS, CPIAUCSL, UNRATE, GDP, "
        "DGS10), each with its observation date, value, unit, and frequency. Reports "
        "`available: false` for an untracked or not-yet-ingested series, never a fabricated "
        "value — this deployment's own economic indicators, independent of any stock.",
        MacroSeriesInput,
        _get_macro_indicators,
    ),
    Tool(
        "get_data_source_status",
        "Get this deployment's data provider configuration and health (which provider is "
        "configured per category, whether a required credential is present, last success/"
        "failure). Never exposes a credential value — only whether one is configured.",
        EmptyInput,
        _get_data_source_status,
    ),
]

TOOLS_BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}
