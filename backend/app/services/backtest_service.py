"""Portfolio backtest serving: tickers + date range + strategy assumptions
-> `ml.inference.serving.generate_historical_predictions` -> `ml.backtest`.
Same rule as `forecast_service.py` (ADR-001): loads already-trained
artifacts and runs `ml.backtest`'s pure functions — never trains anything.

Same data-environment disclosure as `forecast_service.py`: whatever this
deployment's `price_bars` hold (Demo Mode's synthetic data by default) is
what the backtest replays — real data, if this deployment is ever pointed
at a real provider, but never fabricated for the backtest itself. Every
response reports which `data_source`(s) were actually used.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from ml.backtest.engine import run_portfolio_backtest
from ml.backtest.signals import classification_signal
from ml.inference import serving
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.repositories.price_bar_repository import PriceBarRepository
from app.repositories.security_repository import SecurityRepository
from app.services import ml_common

MAX_TICKERS_PER_BACKTEST = 20


def _fetch_multi_ticker_ohlcv(
    db: Session, tickers: list[str], *, start: date, end: date
) -> tuple[pd.DataFrame, list[str]]:
    securities_repo = SecurityRepository(db)
    price_bars_repo = PriceBarRepository(db)

    rows: list[dict] = []
    data_sources: set[str] = set()
    for ticker in tickers:
        security = securities_repo.get_by_ticker(ticker)
        if security is None:
            raise NotFoundError(f"No stock found for ticker '{ticker}'.", code="STOCK_NOT_FOUND")
        data_sources.add(security.data_source)
        bars = price_bars_repo.get_range(
            security_id=security.id,
            start=pd.Timestamp(start, tz="UTC").to_pydatetime(),
            end=pd.Timestamp(end, tz="UTC").to_pydatetime(),
        )
        rows.extend(
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
        )
    return pd.DataFrame(rows), sorted(data_sources)


def run_backtest(
    db: Session,
    *,
    tickers: list[str],
    start_date: date,
    end_date: date,
    commission_bps: float,
    slippage_bps: float,
    initial_capital: float,
    max_position_weight: float | None,
) -> dict:
    if len(tickers) > MAX_TICKERS_PER_BACKTEST:
        raise AppError(
            f"At most {MAX_TICKERS_PER_BACKTEST} tickers per backtest (got {len(tickers)}).",
            code="TOO_MANY_TICKERS",
            status_code=422,
        )

    ohlcv, data_sources = _fetch_multi_ticker_ohlcv(db, tickers, start=start_date, end=end_date)

    try:
        models = ml_common.load_models()
        historical = serving.generate_historical_predictions(ohlcv, models)
    except serving.ServingError as exc:
        raise ml_common.wrap_serving_error(exc) from exc

    bars = historical.rename(columns={"predicted_class": "prediction"})[
        ["ticker", "ts", "price", "prediction"]
    ]
    try:
        result = run_portfolio_backtest(
            bars,
            signal_fn=classification_signal,
            initial_capital=initial_capital,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_position_weight=max_position_weight,
        )
    except ValueError as exc:
        # `bars` is always well-formed here (built from `historical` a few
        # lines up, with fixed, correct column names) — the only
        # `ValueError`s `run_portfolio_backtest` can actually raise against
        # this call site are "empty" or "fewer than 2 distinct trading
        # days", both genuinely insufficient-history conditions (e.g. the
        # requested date range has too little overlap with a ticker's
        # available bars), not a column/schema bug.
        raise ml_common.InsufficientHistoryError(str(exc)) from exc

    equity_curve = [
        {
            "ts": ts,
            "equity": float(equity),
            "benchmark_equity": float(result.benchmark_equity_curve.loc[ts]),
        }
        for ts, equity in result.equity_curve.items()
    ]

    return {
        "tickers": sorted(set(historical["ticker"])),
        "start_date": start_date,
        "end_date": end_date,
        "model_name": "xgboost_direction",
        "model_version": models.direction_record["version"],
        "feature_version": models.direction_record["feature_version"],
        "dataset_version": models.dataset_version,
        "commission_bps": commission_bps,
        "slippage_bps": slippage_bps,
        "initial_capital": initial_capital,
        "equity_curve": equity_curve,
        "metrics": result.metrics.as_dict(),
        "num_rebalance_events": len(result.rebalance_events),
        "data_sources": data_sources,
    }
