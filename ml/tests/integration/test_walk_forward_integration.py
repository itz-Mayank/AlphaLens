"""Integration test for the one deterministic, actually-executed
walk-forward experiment (`ml.backtest.walk_forward.run_xgboost_return_walk_forward`),
run against the REAL research dataset — proving this is genuinely executed
retraining across multiple rolling windows, not just the framework."""

from __future__ import annotations

from ml.backtest.walk_forward import generate_rolling_windows, run_xgboost_return_walk_forward
from ml.data.research_provider import SampleSP500ResearchProvider
from ml.models.xgboost.model import XGBoostHyperparameters


def test_walk_forward_retrains_and_evaluates_across_multiple_real_windows():
    provider = SampleSP500ResearchProvider()
    _, provenance = provider.load()

    windows = generate_rolling_windows(
        start_date=provenance.start_date,
        end_date=provenance.end_date,
        train_days=1000,
        validation_days=180,
        test_days=180,
        step_days=250,
    )
    assert len(windows) >= 2, "expected at least 2 windows from a 5-year real dataset"

    results = run_xgboost_return_walk_forward(
        provider,
        tickers=provenance.tickers,
        windows=windows,
        hyperparameters=XGBoostHyperparameters(n_estimators=50),
    )

    assert len(results) == len(windows)
    for window_result in results:
        assert window_result.num_test_rows > 0
        assert window_result.test_metrics.mae >= 0
        assert window_result.test_metrics.rmse >= 0

    # Each window's test period is later than the previous window's —
    # genuinely walking forward, not re-scoring the same period.
    for earlier, later in zip(results, results[1:], strict=False):
        assert later.window.test_end > earlier.window.test_end

    # A real experiment produces different metrics per window (different
    # market regimes) — not the same number copy-pasted, which would
    # suggest the "retraining" wasn't actually happening per window.
    maes = [r.test_metrics.mae for r in results]
    assert len(set(maes)) > 1
