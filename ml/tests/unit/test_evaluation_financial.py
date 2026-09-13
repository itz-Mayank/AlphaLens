import numpy as np
import pandas as pd
import pytest
from ml.evaluation.financial import (
    DEFAULT_COST_BPS,
    TRADING_DAYS_PER_YEAR,
    evaluate_strategy,
    evaluate_strategy_per_ticker,
)


def test_cumulative_and_benchmark_return_match_independent_calculation():
    """Cross-checked against a from-scratch reimplementation of the
    strategy's own documented rules (signal = sign of forecast, cost
    charged only when the position changes) — not against hand-computed
    numbers, which risks the test itself containing an arithmetic slip."""
    forecasts = pd.Series([0.01, 0.02, -0.01, -0.02])
    actual_next_day = pd.Series([0.02, 0.01, -0.03, 0.01])
    cost_bps = 10.0

    metrics = evaluate_strategy(
        forecasts=forecasts, actual_next_day_returns=actual_next_day, cost_bps=cost_bps
    )

    signal = (forecasts > 0).astype(int)
    changed = signal.diff().fillna(signal.iloc[0]).abs().astype(bool)
    expected_strategy_returns = signal * actual_next_day - changed * (cost_bps / 10_000)
    expected_cumulative = float((1 + expected_strategy_returns).prod() - 1)
    expected_benchmark_cumulative = float((1 + actual_next_day).prod() - 1)

    assert metrics.cumulative_return == pytest.approx(expected_cumulative)
    assert metrics.benchmark_cumulative_return == pytest.approx(expected_benchmark_cumulative)


def test_transaction_costs_reduce_net_return_relative_to_zero_cost():
    forecasts = pd.Series([0.01, 0.01, 0.01, 0.01])
    actual = pd.Series([0.001, 0.001, 0.001, 0.001])

    with_cost = evaluate_strategy(
        forecasts=forecasts, actual_next_day_returns=actual, cost_bps=50.0
    )
    without_cost = evaluate_strategy(
        forecasts=forecasts, actual_next_day_returns=actual, cost_bps=0.0
    )

    assert with_cost.cumulative_return < without_cost.cumulative_return


def test_cost_is_charged_only_on_position_changes_not_every_day():
    """A long position held for 10 straight days should only pay the
    entry cost once (well, entry+eventual exit), not 10 times — this is
    what distinguishes 'transaction cost' from 'holding cost'."""
    forecasts = pd.Series([0.01] * 10)  # always bullish -> long every day, never re-entering
    actual = pd.Series([0.0] * 10)  # zero market return, isolates the cost effect

    metrics = evaluate_strategy(forecasts=forecasts, actual_next_day_returns=actual, cost_bps=100.0)

    # Only one position-change event (flat -> long on day 0); cost charged once.
    expected_cost = 100.0 / 10_000
    assert metrics.cumulative_return == pytest.approx(-expected_cost, abs=1e-9)


def test_always_flat_strategy_has_zero_return_and_no_trades():
    forecasts = pd.Series([-0.01, -0.02, -0.01])
    actual = pd.Series([0.05, -0.05, 0.02])  # market moves, but we're never in it
    metrics = evaluate_strategy(forecasts=forecasts, actual_next_day_returns=actual)
    assert metrics.cumulative_return == pytest.approx(0.0)
    assert metrics.num_trades == 0
    assert metrics.win_rate is None
    assert metrics.profit_factor is None


def test_max_drawdown_is_non_positive_and_zero_for_a_monotonically_up_strategy():
    forecasts = pd.Series([0.01] * 5)
    actual = pd.Series([0.01, 0.02, 0.01, 0.03, 0.01])
    metrics = evaluate_strategy(forecasts=forecasts, actual_next_day_returns=actual, cost_bps=0.0)
    assert metrics.max_drawdown <= 0.0
    assert metrics.max_drawdown == pytest.approx(0.0, abs=1e-9)


def test_win_rate_and_profit_factor_over_two_trades_one_win_one_loss():
    # Trade 1 (days 0-1): long, net positive. Trade 2 (days 3-4): long, net negative.
    forecasts = pd.Series([0.01, 0.01, -0.01, 0.01, 0.01])
    actual = pd.Series([0.05, 0.05, 0.00, -0.10, -0.02])
    metrics = evaluate_strategy(forecasts=forecasts, actual_next_day_returns=actual, cost_bps=0.0)
    assert metrics.num_trades == 2
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.profit_factor is not None
    assert metrics.profit_factor > 0


def test_sharpe_and_sortino_are_none_when_returns_have_zero_variance():
    forecasts = pd.Series([-0.01] * 5)  # always flat
    actual = pd.Series([0.0] * 5)
    metrics = evaluate_strategy(forecasts=forecasts, actual_next_day_returns=actual)
    assert metrics.sharpe_ratio is None
    assert metrics.sortino_ratio is None


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError, match="same length"):
        evaluate_strategy(
            forecasts=pd.Series([0.01, 0.02]), actual_next_day_returns=pd.Series([0.01])
        )


def test_empty_input_raises():
    with pytest.raises(ValueError, match="zero rows"):
        evaluate_strategy(
            forecasts=pd.Series([], dtype=float), actual_next_day_returns=pd.Series([], dtype=float)
        )


def test_default_cost_and_trading_days_constants_are_reasonable():
    assert DEFAULT_COST_BPS > 0
    assert TRADING_DAYS_PER_YEAR == 252


class TestEvaluateStrategyPerTicker:
    def test_matches_calling_evaluate_strategy_once_per_ticker(self):
        """The whole point of the per-ticker function is to be equivalent
        to running `evaluate_strategy` on each ticker's own rows in
        isolation — this cross-checks that directly."""
        tickers = ["AAA"] * 4 + ["BBB"] * 4
        forecasts = pd.Series([0.01, 0.02, -0.01, -0.02, -0.01, 0.03, 0.01, -0.02])
        actual = pd.Series([0.02, 0.01, -0.03, 0.01, 0.04, -0.01, 0.02, 0.03])

        result = evaluate_strategy_per_ticker(
            tickers=tickers, forecasts=forecasts, actual_next_day_returns=actual
        )

        expected_aaa = evaluate_strategy(
            forecasts=forecasts.iloc[:4].reset_index(drop=True),
            actual_next_day_returns=actual.iloc[:4].reset_index(drop=True),
        )
        expected_bbb = evaluate_strategy(
            forecasts=forecasts.iloc[4:].reset_index(drop=True),
            actual_next_day_returns=actual.iloc[4:].reset_index(drop=True),
        )
        assert result["per_ticker"]["AAA"] == expected_aaa.as_dict()
        assert result["per_ticker"]["BBB"] == expected_bbb.as_dict()

    def test_a_trade_never_spans_a_ticker_boundary(self):
        """A naive concatenate-then-evaluate approach would see one
        continuous long position across this exact boundary (AAA ends
        long, BBB starts long) and count it as a single trade compounding
        both instruments' returns. Per-ticker evaluation must not."""
        tickers = ["AAA", "AAA", "BBB", "BBB"]
        forecasts = pd.Series([0.01, 0.01, 0.01, 0.01])  # long the whole time, both tickers
        actual = pd.Series([0.10, 0.10, -0.50, -0.50])  # AAA up big, BBB down big

        result = evaluate_strategy_per_ticker(
            tickers=tickers, forecasts=forecasts, actual_next_day_returns=actual
        )

        assert result["per_ticker"]["AAA"]["num_trades"] == 1
        assert result["per_ticker"]["BBB"]["num_trades"] == 1
        # AAA's trade return must reflect only AAA's +10%/+10% days, never
        # BBB's -50%/-50% days (a concatenated single trade would net
        # these together into one badly-mixed number).
        assert result["per_ticker"]["AAA"]["cumulative_return"] > 0
        assert result["per_ticker"]["BBB"]["cumulative_return"] < 0

    def test_aggregate_means_are_computed_across_tickers(self):
        tickers = ["AAA"] * 3 + ["BBB"] * 3
        forecasts = pd.Series([0.01, 0.01, 0.01, 0.01, 0.01, 0.01])
        actual = pd.Series([0.01, 0.01, 0.01, 0.02, 0.02, 0.02])

        result = evaluate_strategy_per_ticker(
            tickers=tickers, forecasts=forecasts, actual_next_day_returns=actual
        )
        expected_mean = (
            result["per_ticker"]["AAA"]["cumulative_return"]
            + result["per_ticker"]["BBB"]["cumulative_return"]
        ) / 2
        assert result["aggregate"]["cumulative_return_mean"] == pytest.approx(expected_mean)
        assert result["aggregate"]["num_tickers_evaluated"] == 2
        assert result["aggregate"]["num_trades_total"] == (
            result["per_ticker"]["AAA"]["num_trades"] + result["per_ticker"]["BBB"]["num_trades"]
        )

    def test_rows_with_nan_actual_return_are_excluded_per_ticker(self):
        tickers = ["AAA", "AAA", "AAA"]
        forecasts = pd.Series([0.01, 0.01, 0.01])
        actual = pd.Series([0.01, np.nan, 0.01])

        result = evaluate_strategy_per_ticker(
            tickers=tickers, forecasts=forecasts, actual_next_day_returns=actual
        )
        # Only 2 valid rows feed the single ticker's evaluation.
        expected = evaluate_strategy(
            forecasts=pd.Series([0.01, 0.01]), actual_next_day_returns=pd.Series([0.01, 0.01])
        )
        assert result["per_ticker"]["AAA"] == expected.as_dict()

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            evaluate_strategy_per_ticker(
                tickers=["AAA", "AAA"],
                forecasts=pd.Series([0.01]),
                actual_next_day_returns=pd.Series([0.01]),
            )

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="zero rows"):
            evaluate_strategy_per_ticker(
                tickers=[],
                forecasts=pd.Series([], dtype=float),
                actual_next_day_returns=pd.Series([], dtype=float),
            )
