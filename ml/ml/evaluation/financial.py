"""Financial evaluation, from one explicitly-defined strategy — never
"Sharpe ratio of the model's raw predictions" (a meaningless phrase: a
Sharpe ratio describes a *return stream*, which only exists once you've
committed to entry/exit/sizing rules).

STRATEGY DEFINITION (see docs/ml-pipeline.md "Financial evaluation methodology"
for the full write-up):

- **Entry rule:** at the close of day `t`, if the model's forecast (made
  from features known at `t`) is positive, go long starting the next
  trading day; otherwise stay flat. Forecast sign, not magnitude — no
  confidence-weighted sizing (see position sizing, below).
- **Exit rule:** the position (if any) marks to market daily and is
  re-decided every day from the latest forecast — there is no fixed
  holding period despite the model itself forecasting an `h`-day-ahead
  return; using it as a daily rebalancing signal avoids the overlapping,
  double-counted return-accounting problems of literally holding
  `horizon_days`-long positions that open on every single day.
- **Position sizing:** binary — fully invested (long) or fully in cash
  (flat). No leverage, no shorting, no confidence-based sizing.
- **Transaction costs & slippage:** one combined `cost_bps` (default 10
  bps = 0.10%), charged only when the position *changes* (flat->long or
  long->flat), applied against that day's benchmark return magnitude —
  approximates commission + bid-ask spread + slippage together, since
  modeling them separately would need order-book data this pipeline
  doesn't have. Charging it on unchanged days would be wrong (no trade
  happened); this module never does that.
- **Benchmark:** buy-and-hold (always long) over the identical evaluation
  window.
- **Rebalance frequency:** daily.

This is a foundation for a real backtest engine, not a portfolio product —
see docs/ml-pipeline.md "Known limitations" for what's deliberately not
modeled (multi-asset position sizing, borrow costs for shorting, intraday
execution prices).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
DEFAULT_COST_BPS = 10.0


@dataclass(frozen=True)
class FinancialMetrics:
    cumulative_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float
    win_rate: float | None
    profit_factor: float | None
    num_trades: int
    benchmark_cumulative_return: float

    def as_dict(self) -> dict:
        return {
            "cumulative_return": self.cumulative_return,
            "annualized_return": self.annualized_return,
            "annualized_volatility": self.annualized_volatility,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "num_trades": self.num_trades,
            "benchmark_cumulative_return": self.benchmark_cumulative_return,
        }


def _annualized_return(cumulative_return: float, num_days: int) -> float:
    if num_days == 0:
        return 0.0
    return (1 + cumulative_return) ** (TRADING_DAYS_PER_YEAR / num_days) - 1


def _max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    return float(drawdown.min())


def _extract_trades(signal: pd.Series, realized_returns: pd.Series) -> list[float]:
    """One entry per contiguous long segment: that segment's compounded
    net-of-cost return. Used for win rate / profit factor, which are
    trade-level concepts, not daily-return-level ones."""
    trades: list[float] = []
    in_trade = False
    trade_returns: list[float] = []
    for is_long, day_return in zip(signal, realized_returns, strict=True):
        if is_long and not in_trade:
            in_trade = True
            trade_returns = []
        if is_long:
            trade_returns.append(day_return)
        if not is_long and in_trade:
            trades.append(float(np.prod([1 + r for r in trade_returns]) - 1))
            in_trade = False
    if in_trade:
        trades.append(float(np.prod([1 + r for r in trade_returns]) - 1))
    return trades


def evaluate_strategy_per_ticker(
    *,
    tickers,
    forecasts,
    actual_next_day_returns,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict:
    """Runs `evaluate_strategy` independently per ticker and reports both
    the per-ticker breakdown and simple cross-ticker averages.

    This is NOT the same as concatenating every ticker's rows into one
    series and calling `evaluate_strategy` once on the result — that naive
    approach lets a "trade" span a ticker boundary (e.g. a long position
    that was really "long AAPL" silently continues as "long AMZN" the
    next row) and compounds unrelated instruments' daily returns into one
    equity curve, which corresponds to no real, executable strategy. This
    function keeps every ticker's equity curve, trade list, and cost
    accounting fully separate; only the summary statistics are averaged
    across tickers afterward.

    Still not a portfolio backtest — no cross-ticker capital allocation,
    rebalancing, or correlation is modeled (equal, independent, fully-
    invested-or-flat exposure to each name). See docs/ml-pipeline.md
    "Known limitations".
    """
    tickers_arr = np.asarray(tickers)
    forecasts_series = pd.Series(np.asarray(forecasts))
    actual_series = pd.Series(np.asarray(actual_next_day_returns))
    if not (len(tickers_arr) == len(forecasts_series) == len(actual_series)):
        raise ValueError("tickers, forecasts, and actual_next_day_returns must be the same length")
    if len(tickers_arr) == 0:
        raise ValueError("evaluate_strategy_per_ticker() called with zero rows")

    per_ticker: dict[str, dict] = {}
    for ticker in pd.unique(tickers_arr):
        mask = tickers_arr == ticker
        ticker_forecasts = forecasts_series[mask].reset_index(drop=True)
        ticker_actual = actual_series[mask].reset_index(drop=True)
        valid = ticker_forecasts.notna() & ticker_actual.notna()
        if valid.sum() == 0:
            continue
        metrics = evaluate_strategy(
            forecasts=ticker_forecasts[valid].reset_index(drop=True),
            actual_next_day_returns=ticker_actual[valid].reset_index(drop=True),
            cost_bps=cost_bps,
        )
        per_ticker[str(ticker)] = metrics.as_dict()

    def _mean(key: str) -> float | None:
        values = [m[key] for m in per_ticker.values() if m[key] is not None]
        return float(np.mean(values)) if values else None

    aggregate = {
        "cumulative_return_mean": _mean("cumulative_return"),
        "annualized_return_mean": _mean("annualized_return"),
        "sharpe_ratio_mean": _mean("sharpe_ratio"),
        "sortino_ratio_mean": _mean("sortino_ratio"),
        "max_drawdown_mean": _mean("max_drawdown"),
        "win_rate_mean": _mean("win_rate"),
        "profit_factor_mean": _mean("profit_factor"),
        "num_trades_total": sum(m["num_trades"] for m in per_ticker.values()),
        "benchmark_cumulative_return_mean": _mean("benchmark_cumulative_return"),
        "num_tickers_evaluated": len(per_ticker),
    }
    return {"per_ticker": per_ticker, "aggregate": aggregate}


def evaluate_strategy(
    *,
    forecasts: pd.Series,
    actual_next_day_returns: pd.Series,
    cost_bps: float = DEFAULT_COST_BPS,
) -> FinancialMetrics:
    """`forecasts[t]` is the model's forecast made at the close of day `t`
    (any sign-bearing number — a forecast return, or a class turned into
    +1/0/-1). `actual_next_day_returns[t]` is the REAL realized return from
    day `t` to day `t+1`. Both indexed identically and already aligned by
    the caller — this function does no shifting itself, to keep the one
    place a future-vs-past alignment mistake could happen (the caller)
    separate from the arithmetic (here).
    """
    if len(forecasts) != len(actual_next_day_returns):
        raise ValueError("forecasts and actual_next_day_returns must be the same length")
    if len(forecasts) == 0:
        raise ValueError("evaluate_strategy() called with zero rows")

    signal = (forecasts > 0).astype(int)
    cost_fraction = cost_bps / 10_000
    position_changed = signal.diff().fillna(signal.iloc[0]).abs().astype(bool)

    gross_returns = signal * actual_next_day_returns
    strategy_returns = gross_returns - position_changed * cost_fraction

    equity_curve = (1 + strategy_returns).cumprod()
    benchmark_equity_curve = (1 + actual_next_day_returns).cumprod()

    cumulative_return = float(equity_curve.iloc[-1] - 1)
    num_days = len(strategy_returns)
    annualized_vol = float(strategy_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))

    sharpe = None
    if strategy_returns.std(ddof=1) > 0:
        sharpe = float(
            (strategy_returns.mean() * TRADING_DAYS_PER_YEAR)
            / (strategy_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
        )

    downside = strategy_returns[strategy_returns < 0]
    sortino = None
    if len(downside) > 0 and downside.std(ddof=1) > 0:
        sortino = float(
            (strategy_returns.mean() * TRADING_DAYS_PER_YEAR)
            / (downside.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
        )

    trades = _extract_trades(signal.astype(bool), strategy_returns)
    win_rate = None
    profit_factor = None
    if trades:
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t < 0]
        win_rate = len(wins) / len(trades)
        if losses:
            profit_factor = float(sum(wins) / abs(sum(losses))) if wins else 0.0

    return FinancialMetrics(
        cumulative_return=cumulative_return,
        annualized_return=_annualized_return(cumulative_return, num_days),
        annualized_volatility=annualized_vol,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=_max_drawdown(equity_curve),
        win_rate=win_rate,
        profit_factor=profit_factor,
        num_trades=len(trades),
        benchmark_cumulative_return=float(benchmark_equity_curve.iloc[-1] - 1),
    )
