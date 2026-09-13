"""Input/output data contracts for `ml.backtest.engine`.

Deliberately separate from `ml.evaluation.financial`'s per-ticker strategy
evaluation: that module answers "how would this one ticker's signal have
performed in isolation" (Phase 5, ADR-018); this package answers "how
would a portfolio holding several tickers together, sized and rebalanced
as one account, have performed" (Phase 6, see docs/ml-pipeline.md
'Portfolio backtest methodology').
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from ml.backtest.metrics import PortfolioMetrics

REQUIRED_BAR_COLUMNS = ("ticker", "ts", "price")


@dataclass(frozen=True)
class RebalanceEvent:
    """One (ticker, day) weight change — the portfolio-level analogue of a
    single-asset "trade". Not paired into open/close round trips (that
    concept is already covered per-ticker by
    `ml.evaluation.financial.evaluate_strategy_per_ticker`); this is a
    ledger of every notional adjustment the engine made and what it cost."""

    ticker: str
    ts: date
    weight_before: float
    weight_after: float
    cost: float


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.Series  # indexed by ts, starting at `initial_capital`
    benchmark_equity_curve: pd.Series  # equal-weight, all-tickers, daily-rebalanced buy-and-hold
    weights_history: pd.DataFrame  # ts x ticker, the target weight decided *as of* that ts
    portfolio_returns: pd.Series  # net-of-cost daily portfolio return, indexed by ts
    turnover: pd.Series  # one-way turnover per day
    transaction_costs: pd.Series  # cost (as a fraction of equity) charged per day
    rebalance_events: list[RebalanceEvent]
    metrics: PortfolioMetrics
