"""The portfolio backtest engine.

STRATEGY DEFINITION (see docs/ml-pipeline.md "Portfolio backtest
methodology" for the full write-up):

- **Signal:** `ml.backtest.signals` maps each `(ticker, day)`'s model
  output to a position direction — long/flat only by default (never
  shorting unless a caller explicitly opts in at the signal layer; this
  engine itself only ever takes long-or-flat positions regardless, v1
  scope).
- **Execution timing — no look-ahead:** a signal decided using information
  available at the close of day `t` is applied to the return realized from
  the close of day `t` to the close of day `t+1` — **never** to the return
  ending at `t` itself (that would be the same close the signal was
  computed from). Concretely: `weights.loc[t]` (this day's target, decided
  from this day's own signal) is multiplied against
  `next_day_return_wide.loc[t]` (the *known-only-in-hindsight* return from
  `t` to `t+1`) — the one deliberate backward-looking `.shift(-1)` in this
  module exists purely to SCORE an already-decided position, mirroring
  `ml.datasets.tabular.add_next_day_return`'s identical, already-tested
  pattern; it is never used to make a decision.
- **Position sizing:** equal weight across every ticker with a long signal
  on a given day (dynamic — more simultaneously-long names means a smaller
  weight each), fully invested only when every eligible name is long,
  otherwise the remainder sits in un-modeled cash. No leverage.
- **Transaction costs & slippage:** `commission_bps` + `slippage_bps`
  (both configurable, non-zero by default), charged against one-way
  turnover (`sum(abs(weight_change)) / 2`) on the same day the rebalance
  happens.
- **Benchmark:** equal-weight, daily-rebalanced buy-and-hold across every
  ticker with a valid price that day — no signal, no transaction costs
  (mirrors `ml.evaluation.financial`'s benchmark treatment).
- **Rebalance frequency:** daily.

This is still not a full brokerage simulation — see docs/ml-pipeline.md
"Known limitations" for what is deliberately not modeled (fractional-share
rounding, market-impact-scaling slippage, intraday fills, borrow costs).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from ml.backtest.contracts import REQUIRED_BAR_COLUMNS, BacktestResult, RebalanceEvent
from ml.backtest.metrics import compute_portfolio_metrics

DEFAULT_INITIAL_CAPITAL = 100_000.0
DEFAULT_COMMISSION_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0


def _target_weights(
    signal_wide: pd.DataFrame, *, max_position_weight: float | None
) -> pd.DataFrame:
    """Equal weight across every ticker with a strictly-positive signal on
    a given day. Negative (short) signals are intentionally treated as
    flat here — see this module's docstring: shorting is a signal-layer
    concept this engine does not act on in v1."""
    long_mask = signal_wide > 0
    n_long = long_mask.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        equal_weight = 1.0 / n_long.replace(0, np.nan)
    weights = long_mask.mul(equal_weight, axis=0).fillna(0.0)
    if max_position_weight is not None:
        weights = weights.clip(upper=max_position_weight)
    return weights


def run_portfolio_backtest(
    bars: pd.DataFrame,
    *,
    signal_fn: Callable[[Any], float] | None = None,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    commission_bps: float = DEFAULT_COMMISSION_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    max_position_weight: float | None = None,
) -> BacktestResult:
    """`bars`: one row per `(ticker, ts)`, columns `ticker, ts, price`, plus
    either a `signal` column (values in `{-1, 0, 1}`, already decided) or a
    `prediction` column and a `signal_fn` to derive one
    (`ml.backtest.signals.classification_signal`/`return_sign_signal`).
    `price` must be the closing price used to make that day's decision —
    see this module's docstring for the execution-timing guarantee this
    implies.

    Raises `ValueError` on missing columns, empty input, or fewer than 2
    distinct trading days (there is no return to realize from a single
    day).
    """
    missing = set(REQUIRED_BAR_COLUMNS) - set(bars.columns)
    if missing:
        raise ValueError(f"bars is missing required columns: {sorted(missing)}")
    if bars.empty:
        raise ValueError("run_portfolio_backtest() called with zero rows")

    df = bars.sort_values(["ticker", "ts"]).reset_index(drop=True).copy()
    if signal_fn is not None:
        df["signal"] = df["prediction"].apply(signal_fn)
    elif "signal" not in df.columns:
        raise ValueError(
            "bars must have a 'signal' column, or pass signal_fn to derive one from 'prediction'"
        )

    price_wide = df.pivot(index="ts", columns="ticker", values="price").sort_index()
    signal_wide = (
        df.pivot(index="ts", columns="ticker", values="signal")
        .sort_index()
        .reindex(columns=price_wide.columns)
        .fillna(0.0)
    )

    if len(price_wide.index) < 2:
        raise ValueError("run_portfolio_backtest() needs at least 2 distinct trading days")

    # The one deliberate negative shift in this module — see the module
    # docstring's "Execution timing" section for why this is scoring, not
    # deciding.
    next_day_return_wide = price_wide.pct_change().shift(-1)

    weights = _target_weights(signal_wide, max_position_weight=max_position_weight)
    prior_weights = weights.shift(1).fillna(0.0)
    turnover = (weights - prior_weights).abs().sum(axis=1) / 2.0
    cost_fraction = (commission_bps + slippage_bps) / 10_000
    transaction_costs = turnover * cost_fraction

    gross_portfolio_return = (weights * next_day_return_wide).sum(axis=1, skipna=True, min_count=1)

    # The last trading day has no known next-day return — dropped, never
    # fabricated as zero (same principle as `ml.targets.targets.future_return`).
    usable_index = next_day_return_wide.dropna(how="all").index
    portfolio_returns = (
        gross_portfolio_return.loc[usable_index] - transaction_costs.loc[usable_index]
    ).fillna(0.0)
    turnover = turnover.loc[usable_index]
    transaction_costs = transaction_costs.loc[usable_index]
    weights = weights.loc[usable_index]

    equity_curve = initial_capital * (1 + portfolio_returns).cumprod()

    active = price_wide.notna()
    n_active = active.sum(axis=1).replace(0, np.nan)
    benchmark_weights = active.div(n_active, axis=0).fillna(0.0)
    benchmark_gross_return = (
        (benchmark_weights * next_day_return_wide)
        .sum(axis=1, skipna=True, min_count=1)
        .loc[usable_index]
        .fillna(0.0)
    )
    benchmark_equity_curve = initial_capital * (1 + benchmark_gross_return).cumprod()

    rebalance_events = _extract_rebalance_events(
        weights, prior_weights.loc[usable_index], transaction_costs
    )

    metrics = compute_portfolio_metrics(
        portfolio_returns=portfolio_returns,
        equity_curve=equity_curve,
        benchmark_returns=benchmark_gross_return,
        benchmark_equity_curve=benchmark_equity_curve,
        turnover=turnover,
        transaction_costs=transaction_costs,
    )

    return BacktestResult(
        equity_curve=equity_curve,
        benchmark_equity_curve=benchmark_equity_curve,
        weights_history=weights,
        portfolio_returns=portfolio_returns,
        turnover=turnover,
        transaction_costs=transaction_costs,
        rebalance_events=rebalance_events,
        metrics=metrics,
    )


def _extract_rebalance_events(
    weights: pd.DataFrame, prior_weights: pd.DataFrame, transaction_costs: pd.Series
) -> list[RebalanceEvent]:
    events: list[RebalanceEvent] = []
    changed = (weights - prior_weights).abs() > 1e-12
    for ts in weights.index:
        row_changed = changed.loc[ts]
        tickers_changed = row_changed[row_changed].index
        if len(tickers_changed) == 0:
            continue
        # Split this day's total cost proportionally across the tickers
        # that actually changed, by their share of this day's turnover —
        # bookkeeping only, the portfolio-level `transaction_costs` series
        # (used by the metrics) is the authoritative total.
        day_turnover = (weights.loc[ts] - prior_weights.loc[ts]).abs().sum() / 2.0
        for ticker in tickers_changed:
            weight_delta = abs(weights.loc[ts, ticker] - prior_weights.loc[ts, ticker])
            share = (weight_delta / 2.0) / day_turnover if day_turnover > 0 else 0.0
            events.append(
                RebalanceEvent(
                    ticker=ticker,
                    ts=ts,
                    weight_before=float(prior_weights.loc[ts, ticker]),
                    weight_after=float(weights.loc[ts, ticker]),
                    cost=float(transaction_costs.loc[ts] * share),
                )
            )
    return events
