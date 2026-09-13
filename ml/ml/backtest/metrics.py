"""Portfolio-level risk/return metrics, computed from one equity curve.

Formulas mirror `ml.evaluation.financial`'s single-asset versions (same
definitions of Sharpe/Sortino/max-drawdown/CAGR) — duplicated rather than
imported because that module's functions are scoped to a single ticker's
strategy evaluation, while these operate on a portfolio-level equity curve
that already blends multiple tickers together; sharing the numeric
definition, not the code path, is what actually matters for consistency.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PortfolioMetrics:
    cumulative_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float
    win_rate: float | None
    turnover_mean: float
    total_transaction_costs: float
    num_rebalance_days: int
    benchmark_cumulative_return: float

    def as_dict(self) -> dict:
        return {
            "cumulative_return": self.cumulative_return,
            "cagr": self.cagr,
            "annualized_volatility": self.annualized_volatility,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "turnover_mean": self.turnover_mean,
            "total_transaction_costs": self.total_transaction_costs,
            "num_rebalance_days": self.num_rebalance_days,
            "benchmark_cumulative_return": self.benchmark_cumulative_return,
        }


def _cagr(cumulative_return: float, num_days: int) -> float:
    if num_days == 0:
        return 0.0
    return (1 + cumulative_return) ** (TRADING_DAYS_PER_YEAR / num_days) - 1


def _max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    return float(drawdown.min())


def compute_portfolio_metrics(
    *,
    portfolio_returns: pd.Series,
    equity_curve: pd.Series,
    benchmark_returns: pd.Series,
    benchmark_equity_curve: pd.Series,
    turnover: pd.Series,
    transaction_costs: pd.Series,
) -> PortfolioMetrics:
    """`portfolio_returns`/`equity_curve`/`turnover`/`transaction_costs` are
    all indexed identically (one row per trading day the backtest ran
    over). Handles the documented edge cases explicitly rather than
    returning a silent `NaN`:

    - Zero variance in `portfolio_returns` (e.g. never held a position) ->
      `sharpe_ratio`/`sortino_ratio` are `None`, not `inf`/`NaN`.
    - No down days -> `sortino_ratio` is `None` (no downside deviation to
      divide by), not a fabricated large number.
    - Empty input -> raises `ValueError` rather than returning a report
      full of `NaN`/zeroes that would look like a real (flat) result.
    """
    if len(portfolio_returns) == 0:
        raise ValueError("compute_portfolio_metrics() called with zero rows")

    # Computed from the returns series directly (a compounded product),
    # never as `equity_curve.iloc[-1] / equity_curve.iloc[0]` — with
    # exactly one usable day those two `equity_curve` values are the same
    # number (both `initial_capital * (1 + returns.iloc[0])`), which would
    # silently report a real, nonzero single-day return as a 0% cumulative
    # return.
    cumulative_return = float((1 + portfolio_returns).prod() - 1)
    num_days = len(portfolio_returns)

    std = portfolio_returns.std(ddof=1)
    annualized_vol = float(std * np.sqrt(TRADING_DAYS_PER_YEAR)) if pd.notna(std) else 0.0

    sharpe = None
    if pd.notna(std) and std > 0:
        sharpe = float(
            (portfolio_returns.mean() * TRADING_DAYS_PER_YEAR)
            / (std * np.sqrt(TRADING_DAYS_PER_YEAR))
        )

    downside = portfolio_returns[portfolio_returns < 0]
    sortino = None
    if len(downside) > 0 and downside.std(ddof=1) > 0:
        sortino = float(
            (portfolio_returns.mean() * TRADING_DAYS_PER_YEAR)
            / (downside.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
        )

    non_flat_days = portfolio_returns[portfolio_returns != 0]
    win_rate = float((non_flat_days > 0).mean()) if len(non_flat_days) > 0 else None

    return PortfolioMetrics(
        cumulative_return=cumulative_return,
        cagr=_cagr(cumulative_return, num_days),
        annualized_volatility=annualized_vol,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=_max_drawdown(equity_curve),
        win_rate=win_rate,
        turnover_mean=float(turnover.mean()),
        total_transaction_costs=float(transaction_costs.sum()),
        num_rebalance_days=int((turnover > 0).sum()),
        benchmark_cumulative_return=float((1 + benchmark_returns).prod() - 1),
    )
