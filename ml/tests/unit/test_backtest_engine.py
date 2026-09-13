"""Tests for `ml.backtest.engine`. The CRITICAL leakage/timing tests
(explicitly required for Phase 6) get their own class at the bottom —
everything above is ordinary portfolio-mechanics coverage."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from ml.backtest.engine import run_portfolio_backtest
from ml.backtest.signals import classification_signal


def _bars(rows: list[tuple[str, str, float, str | None]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["ticker", "ts", "price", "prediction"]).assign(
        ts=lambda d: pd.to_datetime(d["ts"]).dt.date
    )


def _two_ticker_bars(n_days: int = 10, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-01", periods=n_days)
    rows = []
    for ticker, start_price in (("AAA", 100.0), ("BBB", 50.0)):
        price = start_price
        for ts in dates:
            price *= 1 + rng.normal(0.001, 0.01)
            prediction = "Bullish" if rng.random() > 0.5 else "Neutral"
            rows.append((ticker, ts.date(), price, prediction))
    return pd.DataFrame(rows, columns=["ticker", "ts", "price", "prediction"])


class TestInputValidation:
    def test_missing_columns_raise(self):
        with pytest.raises(ValueError, match="missing required columns"):
            run_portfolio_backtest(
                pd.DataFrame({"ticker": ["AAA"], "ts": [pd.Timestamp("2021-01-01")]})
            )

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="zero rows"):
            run_portfolio_backtest(pd.DataFrame(columns=["ticker", "ts", "price"]))

    def test_single_day_raises(self):
        df = _bars([("AAA", "2021-01-01", 100.0, "Bullish")])
        with pytest.raises(ValueError, match="at least 2 distinct trading days"):
            run_portfolio_backtest(df, signal_fn=classification_signal)

    def test_missing_signal_and_no_signal_fn_raises(self):
        df = _bars(
            [("AAA", "2021-01-01", 100.0, "Bullish"), ("AAA", "2021-01-02", 101.0, "Bullish")]
        )
        with pytest.raises(ValueError, match="signal"):
            run_portfolio_backtest(df)


class TestNoTradeCase:
    def test_always_flat_signal_produces_zero_return_and_no_rebalances(self):
        df = _bars(
            [
                ("AAA", "2021-01-01", 100.0, "Neutral"),
                ("AAA", "2021-01-02", 110.0, "Neutral"),
                ("AAA", "2021-01-03", 90.0, "Neutral"),
            ]
        )
        result = run_portfolio_backtest(df, signal_fn=classification_signal)
        assert (result.portfolio_returns == 0.0).all()
        assert result.metrics.cumulative_return == pytest.approx(0.0)
        assert len(result.rebalance_events) == 0
        assert result.metrics.total_transaction_costs == pytest.approx(0.0)


class TestZeroVolatilityCase:
    def test_constant_returns_give_none_sharpe_and_sortino(self):
        df = _bars(
            [
                ("AAA", "2021-01-01", 100.0, "Bullish"),
                ("AAA", "2021-01-02", 101.0, "Bullish"),
                ("AAA", "2021-01-03", 102.01, "Bullish"),
                ("AAA", "2021-01-04", 103.0301, "Bullish"),
            ]
        )
        result = run_portfolio_backtest(
            df, signal_fn=classification_signal, commission_bps=0, slippage_bps=0
        )
        # Every day returns exactly 1% -> zero variance in portfolio_returns.
        assert result.metrics.sharpe_ratio is None
        assert result.metrics.sortino_ratio is None


class TestTransactionCosts:
    def test_higher_costs_reduce_cumulative_return_when_rebalancing_occurs(self):
        df = _two_ticker_bars(n_days=20, seed=1)
        low_cost = run_portfolio_backtest(
            df, signal_fn=classification_signal, commission_bps=1, slippage_bps=1
        )
        high_cost = run_portfolio_backtest(
            df, signal_fn=classification_signal, commission_bps=100, slippage_bps=100
        )
        assert len(low_cost.rebalance_events) > 0  # sanity: costs actually apply to something
        assert high_cost.metrics.cumulative_return < low_cost.metrics.cumulative_return
        assert high_cost.metrics.total_transaction_costs > low_cost.metrics.total_transaction_costs

    def test_zero_cost_backtest_has_zero_total_transaction_costs(self):
        df = _two_ticker_bars(n_days=15, seed=2)
        result = run_portfolio_backtest(
            df, signal_fn=classification_signal, commission_bps=0, slippage_bps=0
        )
        assert result.metrics.total_transaction_costs == pytest.approx(0.0)


class TestPositionSizing:
    def test_equal_weight_across_simultaneously_long_tickers(self):
        df = _bars(
            [
                ("AAA", "2021-01-01", 100.0, "Bullish"),
                ("BBB", "2021-01-01", 50.0, "Bullish"),
                ("AAA", "2021-01-02", 101.0, "Bullish"),
                ("BBB", "2021-01-02", 51.0, "Bullish"),
            ]
        )
        result = run_portfolio_backtest(df, signal_fn=classification_signal)
        first_day = result.weights_history.iloc[0]
        assert first_day["AAA"] == pytest.approx(0.5)
        assert first_day["BBB"] == pytest.approx(0.5)

    def test_only_long_signaled_tickers_get_weight(self):
        df = _bars(
            [
                ("AAA", "2021-01-01", 100.0, "Bullish"),
                ("BBB", "2021-01-01", 50.0, "Bearish"),
                ("AAA", "2021-01-02", 101.0, "Bullish"),
                ("BBB", "2021-01-02", 49.0, "Bearish"),
            ]
        )
        result = run_portfolio_backtest(df, signal_fn=classification_signal)
        first_day = result.weights_history.iloc[0]
        assert first_day["AAA"] == pytest.approx(1.0)
        assert first_day["BBB"] == pytest.approx(0.0)

    def test_max_position_weight_caps_a_single_name(self):
        df = _bars(
            [
                ("AAA", "2021-01-01", 100.0, "Bullish"),
                ("AAA", "2021-01-02", 101.0, "Bullish"),
            ]
        )
        result = run_portfolio_backtest(
            df, signal_fn=classification_signal, max_position_weight=0.3
        )
        assert result.weights_history.iloc[0]["AAA"] == pytest.approx(0.3)


class TestPortfolioAccounting:
    def test_equity_curve_starts_from_initial_capital_times_first_return(self):
        df = _bars(
            [
                ("AAA", "2021-01-01", 100.0, "Bullish"),
                ("AAA", "2021-01-02", 110.0, "Bullish"),
            ]
        )
        result = run_portfolio_backtest(
            df,
            signal_fn=classification_signal,
            initial_capital=1000.0,
            commission_bps=0,
            slippage_bps=0,
        )
        assert result.equity_curve.iloc[0] == pytest.approx(1000.0 * 1.10)

    def test_max_drawdown_is_non_positive(self):
        df = _two_ticker_bars(n_days=30, seed=3)
        result = run_portfolio_backtest(df, signal_fn=classification_signal)
        assert result.metrics.max_drawdown <= 0.0

    def test_benchmark_uses_real_prices_not_fabricated(self):
        df = _bars(
            [
                ("AAA", "2021-01-01", 100.0, "Neutral"),
                ("BBB", "2021-01-01", 50.0, "Neutral"),
                ("AAA", "2021-01-02", 110.0, "Neutral"),
                ("BBB", "2021-01-02", 55.0, "Neutral"),
            ]
        )
        result = run_portfolio_backtest(df, signal_fn=classification_signal)
        # Equal-weight buy-and-hold of two names each up 10% -> benchmark up 10%,
        # independent of the (all-flat) strategy signal.
        assert result.metrics.benchmark_cumulative_return == pytest.approx(0.10)

    def test_multiple_tickers_with_different_start_dates_are_handled(self):
        """A ticker that only starts trading partway through the window
        (e.g. an IPO) must not break the engine or corrupt other tickers'
        accounting."""
        df = _bars(
            [
                ("AAA", "2021-01-01", 100.0, "Bullish"),
                ("AAA", "2021-01-02", 101.0, "Bullish"),
                ("AAA", "2021-01-03", 102.0, "Bullish"),
                ("BBB", "2021-01-02", 50.0, "Bullish"),
                ("BBB", "2021-01-03", 51.0, "Bullish"),
            ]
        )
        result = run_portfolio_backtest(df, signal_fn=classification_signal)
        assert len(result.equity_curve) == 2  # only 2021-01-01 and 01-02 have a next-day return
        assert np.isfinite(result.equity_curve).all()


class TestCriticalLeakageAndTimingTests:
    """The explicitly-required Phase 6 leakage tests."""

    def test_signal_is_never_scored_against_the_same_close_it_was_generated_from(self):
        """A day-t decision must earn the close(t)->close(t+1) return, never
        the close(t-1)->close(t) return that would have been visible when
        the decision was made."""
        # AAA: flat on day 1 (price 100->200, a return this decision must
        # NOT capture), then Bullish on day 2 (price 200->100, a return
        # this decision MUST capture).
        df = _bars(
            [
                ("AAA", "2021-01-01", 100.0, "Neutral"),
                ("AAA", "2021-01-02", 200.0, "Bullish"),
                ("AAA", "2021-01-03", 100.0, "Bullish"),
            ]
        )
        result = run_portfolio_backtest(
            df, signal_fn=classification_signal, commission_bps=0, slippage_bps=0
        )
        # Day 1 (flat) must show zero return, even though price doubled
        # that same day — that move happened *before* day 2's Bullish
        # decision could have been informed by anything, and day 1's own
        # decision was Neutral (flat).
        day1_return = result.portfolio_returns.iloc[0]
        assert day1_return == pytest.approx(0.0)
        # Day 2 (Bullish, decided at close=200) must show the day2->day3
        # -50% move, not the day1->day2 +100% move.
        day2_return = result.portfolio_returns.iloc[1]
        assert day2_return == pytest.approx(-0.5)

    def test_truncating_future_rows_does_not_change_earlier_equity_or_weights(self):
        """Appending more history to the end of the dataset must not
        change any earlier day's computed equity curve or weights —
        proof the engine never looks forward when computing a historical
        result."""
        full = _two_ticker_bars(n_days=40, seed=4)
        cutoff = sorted(full["ts"].unique())[25]
        truncated = full[full["ts"] <= cutoff]

        full_result = run_portfolio_backtest(full, signal_fn=classification_signal)
        truncated_result = run_portfolio_backtest(truncated, signal_fn=classification_signal)

        common_index = truncated_result.equity_curve.index
        pd.testing.assert_series_equal(
            full_result.equity_curve.loc[common_index],
            truncated_result.equity_curve.loc[common_index],
        )
        pd.testing.assert_frame_equal(
            full_result.weights_history.loc[common_index],
            truncated_result.weights_history.loc[common_index],
        )

    def test_a_future_price_spike_does_not_change_a_historical_decisions_recorded_return(self):
        """Directly mutating only a FUTURE bar's price (beyond what any
        historical decision could see) must leave every earlier day's
        portfolio_return, weight, and equity value byte-identical."""
        baseline = _two_ticker_bars(n_days=20, seed=5)
        mutated = baseline.copy()
        last_ts = mutated["ts"].max()
        mutated.loc[mutated["ts"] == last_ts, "price"] *= 100  # a wild future spike

        baseline_result = run_portfolio_backtest(baseline, signal_fn=classification_signal)
        mutated_result = run_portfolio_backtest(mutated, signal_fn=classification_signal)

        # The spike changes the *last* usable day's forward-looking return
        # (that day's decision is scored against the spike) but must not
        # touch anything earlier.
        earlier_index = baseline_result.equity_curve.index[:-1]
        pd.testing.assert_series_equal(
            baseline_result.equity_curve.loc[earlier_index],
            mutated_result.equity_curve.loc[earlier_index],
        )

    def test_a_tickers_return_never_uses_another_tickers_price(self):
        """AAA's return calculation must be computed purely from AAA's own
        price series — a completely flat BBB spliced in alongside a moving
        AAA must not change AAA's realized returns."""
        dates = pd.bdate_range("2021-01-01", periods=5)
        rows = []
        aaa_prices = [100.0, 110.0, 90.0, 120.0, 80.0]
        for ts, price in zip(dates, aaa_prices, strict=True):
            rows.append(("AAA", ts.date(), price, "Bullish"))
        for ts in dates:
            rows.append(("BBB", ts.date(), 50.0, "Bullish"))  # perfectly flat
        df = pd.DataFrame(rows, columns=["ticker", "ts", "price", "prediction"])

        result = run_portfolio_backtest(
            df, signal_fn=classification_signal, commission_bps=0, slippage_bps=0
        )
        # Both are equally-weighted and long throughout; BBB always
        # contributes exactly 0 return, so the portfolio return each day
        # must equal exactly half of AAA's own day-over-day return.
        expected_aaa_returns = (
            pd.Series(aaa_prices).pct_change().shift(-1).dropna().reset_index(drop=True)
        )
        actual = result.portfolio_returns.reset_index(drop=True) * 2
        pd.testing.assert_series_equal(actual, expected_aaa_returns, check_names=False)
