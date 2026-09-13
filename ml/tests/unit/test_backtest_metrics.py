"""Tests for `ml.backtest.metrics.compute_portfolio_metrics`, isolated from
the full engine — including a regression test for a real bug found while
building the engine (see the single-day case below)."""

from __future__ import annotations

import pandas as pd
import pytest
from ml.backtest.metrics import compute_portfolio_metrics


def _series(values: list[float], dates: list[str]) -> pd.Series:
    return pd.Series(values, index=pd.to_datetime(dates).date)


class TestComputePortfolioMetrics:
    def test_empty_input_raises(self):
        empty = pd.Series([], dtype=float)
        with pytest.raises(ValueError, match="zero rows"):
            compute_portfolio_metrics(
                portfolio_returns=empty,
                equity_curve=empty,
                benchmark_returns=empty,
                benchmark_equity_curve=empty,
                turnover=empty,
                transaction_costs=empty,
            )

    def test_single_day_cumulative_return_is_not_silently_zeroed(self):
        """Regression test: an earlier version computed cumulative_return
        as `equity_curve.iloc[-1] / equity_curve.iloc[0] - 1`, which is
        trivially 0 whenever there is exactly one usable day (both index
        positions are the same value) — silently hiding a real, nonzero
        single-day return."""
        returns = _series([0.05], ["2021-01-01"])
        equity = 100_000 * (1 + returns).cumprod()
        zero = _series([0.0], ["2021-01-01"])

        metrics = compute_portfolio_metrics(
            portfolio_returns=returns,
            equity_curve=equity,
            benchmark_returns=zero,
            benchmark_equity_curve=100_000 * (1 + zero).cumprod(),
            turnover=zero,
            transaction_costs=zero,
        )
        assert metrics.cumulative_return == pytest.approx(0.05)

    def test_cumulative_return_compounds_multiple_days(self):
        returns = _series([0.10, -0.05, 0.02], ["2021-01-01", "2021-01-02", "2021-01-03"])
        equity = 100_000 * (1 + returns).cumprod()
        zero = _series([0.0] * 3, ["2021-01-01", "2021-01-02", "2021-01-03"])

        metrics = compute_portfolio_metrics(
            portfolio_returns=returns,
            equity_curve=equity,
            benchmark_returns=zero,
            benchmark_equity_curve=100_000 * (1 + zero).cumprod(),
            turnover=zero,
            transaction_costs=zero,
        )
        expected = (1.10 * 0.95 * 1.02) - 1
        assert metrics.cumulative_return == pytest.approx(expected)

    def test_zero_variance_returns_none_sharpe_and_sortino(self):
        returns = _series([0.01, 0.01, 0.01], ["2021-01-01", "2021-01-02", "2021-01-03"])
        equity = 100_000 * (1 + returns).cumprod()
        zero = _series([0.0] * 3, ["2021-01-01", "2021-01-02", "2021-01-03"])

        metrics = compute_portfolio_metrics(
            portfolio_returns=returns,
            equity_curve=equity,
            benchmark_returns=zero,
            benchmark_equity_curve=100_000 * (1 + zero).cumprod(),
            turnover=zero,
            transaction_costs=zero,
        )
        assert metrics.sharpe_ratio is None
        assert metrics.sortino_ratio is None

    def test_no_down_days_gives_none_sortino_but_a_real_sharpe(self):
        returns = _series([0.01, 0.02, 0.005], ["2021-01-01", "2021-01-02", "2021-01-03"])
        equity = 100_000 * (1 + returns).cumprod()
        zero = _series([0.0] * 3, ["2021-01-01", "2021-01-02", "2021-01-03"])

        metrics = compute_portfolio_metrics(
            portfolio_returns=returns,
            equity_curve=equity,
            benchmark_returns=zero,
            benchmark_equity_curve=100_000 * (1 + zero).cumprod(),
            turnover=zero,
            transaction_costs=zero,
        )
        assert metrics.sortino_ratio is None
        assert metrics.sharpe_ratio is not None

    def test_max_drawdown_reflects_a_real_peak_to_trough_decline(self):
        returns = _series([0.10, -0.20, 0.05], ["2021-01-01", "2021-01-02", "2021-01-03"])
        equity = 100_000 * (1 + returns).cumprod()
        zero = _series([0.0] * 3, ["2021-01-01", "2021-01-02", "2021-01-03"])

        metrics = compute_portfolio_metrics(
            portfolio_returns=returns,
            equity_curve=equity,
            benchmark_returns=zero,
            benchmark_equity_curve=100_000 * (1 + zero).cumprod(),
            turnover=zero,
            transaction_costs=zero,
        )
        peak = 1.10
        trough = 1.10 * 0.80
        assert metrics.max_drawdown == pytest.approx(trough / peak - 1)

    def test_total_transaction_costs_and_turnover_pass_through(self):
        returns = _series([0.01, 0.01], ["2021-01-01", "2021-01-02"])
        equity = 100_000 * (1 + returns).cumprod()
        zero = _series([0.0, 0.0], ["2021-01-01", "2021-01-02"])
        turnover = _series([1.0, 0.5], ["2021-01-01", "2021-01-02"])
        costs = _series([0.001, 0.0005], ["2021-01-01", "2021-01-02"])

        metrics = compute_portfolio_metrics(
            portfolio_returns=returns,
            equity_curve=equity,
            benchmark_returns=zero,
            benchmark_equity_curve=100_000 * (1 + zero).cumprod(),
            turnover=turnover,
            transaction_costs=costs,
        )
        assert metrics.total_transaction_costs == pytest.approx(0.0015)
        assert metrics.num_rebalance_days == 2
