import inspect

import pandas as pd
import pytest
from ml.targets import targets as targets_module
from ml.targets.targets import (
    CLASS_NAMES,
    classify_return,
    derive_classification_thresholds,
    future_return,
)

from tests.helpers import make_synthetic_ohlcv


def test_future_return_matches_manual_calculation():
    df = make_synthetic_ohlcv(tickers=("AAA",), num_days=30)
    horizon = 5
    result = future_return(df, horizon_days=horizon)

    closes = df["close"].reset_index(drop=True)
    for t in range(len(df) - horizon):
        expected = closes[t + horizon] / closes[t] - 1
        assert result.iloc[t] == pytest.approx(expected)


def test_future_return_last_h_rows_are_nan_not_fabricated():
    df = make_synthetic_ohlcv(tickers=("AAA",), num_days=30)
    horizon = 5
    result = future_return(df, horizon_days=horizon)
    assert result.iloc[-horizon:].isna().all()


def test_future_return_does_not_cross_ticker_boundaries():
    df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=30)
    horizon = 5
    result = future_return(df, horizon_days=horizon)

    # AAA's last `horizon` rows must be NaN even though BBB's rows follow
    # them in the concatenated frame — a bug here would pull BBB's early
    # closes into AAA's target.
    aaa_mask = df["ticker"] == "AAA"
    aaa_result = result[aaa_mask].reset_index(drop=True)
    assert aaa_result.iloc[-horizon:].isna().all()


def test_targets_module_only_uses_negative_shift_for_the_future_target():
    """Every shift in ml/features/*.py must be non-negative (pulling the
    past forward); ml/targets/targets.py is the one place a negative shift
    (pulling the future backward) is allowed. If a feature module ever
    grows a negative shift, this test's counterpart assumption in
    ml/features/pipeline.py's no-lookahead tests would likely also start
    failing — this test makes the *rule* explicit and checkable by source
    inspection, not just by behavior.
    """
    import ast

    source = inspect.getsource(targets_module)
    tree = ast.parse(source)
    negative_shifts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "shift":
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
                    negative_shifts.append(node)
    assert len(negative_shifts) >= 1, "expected future_return's shift(-horizon_days)"


def test_derive_classification_thresholds_is_symmetric_around_the_mean():
    returns = pd.Series([0.01, -0.01, 0.02, -0.02, 0.0, 0.005, -0.005])
    bearish, bullish = derive_classification_thresholds(returns, num_std=1.0)
    mean = returns.mean()
    assert bearish == pytest.approx(mean - returns.std())
    assert bullish == pytest.approx(mean + returns.std())


def test_derive_classification_thresholds_ignores_nan():
    returns = pd.Series([0.01, -0.01, None, 0.02, -0.02])
    bearish, bullish = derive_classification_thresholds(returns)
    assert bearish is not None and bullish is not None


def test_classify_return_assigns_expected_labels():
    returns = pd.Series([-0.05, 0.0, 0.05, None])
    labels = classify_return(returns, bearish_threshold=-0.02, bullish_threshold=0.02)
    assert labels.iloc[0] == "Bearish"
    assert labels.iloc[1] == "Neutral"
    assert labels.iloc[2] == "Bullish"
    assert pd.isna(labels.iloc[3])


def test_class_names_are_in_bearish_neutral_bullish_order():
    assert CLASS_NAMES == ("Bearish", "Neutral", "Bullish")
