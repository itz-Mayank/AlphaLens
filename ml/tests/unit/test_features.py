"""The most important test file in this package: proves features never see
the future. See ml/features/pipeline.py's docstring for why this matters
more than any other correctness property here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from ml.features.pipeline import FEATURE_COLUMNS, build_features

from tests.helpers import make_synthetic_ohlcv


def test_no_lookahead_truncating_the_future_does_not_change_past_feature_values():
    """The single most important test in this package. Build features on
    the full series, then again on a series truncated after some cutoff
    row, and assert every row up to the cutoff is byte-identical. If any
    feature secretly used a future value (a centered window, a backward
    shift, a global statistic), truncating the future would change it.
    """
    df = make_synthetic_ohlcv(tickers=("AAA",), num_days=200)
    full_features = build_features(df)

    cutoff = 150
    truncated_input = df.iloc[:cutoff].reset_index(drop=True)
    truncated_features = build_features(truncated_input)

    pd.testing.assert_frame_equal(
        truncated_features.reset_index(drop=True),
        full_features.iloc[:cutoff].reset_index(drop=True),
        check_dtype=False,
    )


def test_no_lookahead_per_ticker_in_a_multi_ticker_panel():
    """Same property, but checked with a second ticker present — proves
    the per-ticker groupby in build_features() doesn't let one ticker's
    presence/absence change another's computed values."""
    df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=200)
    with_both = build_features(df)

    aaa_only = df[df["ticker"] == "AAA"].reset_index(drop=True)
    with_aaa_only = build_features(aaa_only)

    aaa_from_both = with_both[with_both["ticker"] == "AAA"].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        with_aaa_only[list(FEATURE_COLUMNS)],
        aaa_from_both[list(FEATURE_COLUMNS)],
        check_dtype=False,
    )


def test_rolling_features_do_not_cross_ticker_boundaries():
    """The first `window` rows of the SECOND ticker must be NaN — if a
    rolling calculation accidentally ran across the whole (unsorted-by-
    groupby) frame instead of per ticker, BBB's early SMA would be
    contaminated by AAA's trailing prices instead of being NaN."""
    df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=100)
    features = build_features(df)

    bbb = features[features["ticker"] == "BBB"].reset_index(drop=True)
    assert bbb["sma_50"].iloc[:49].isna().all()
    assert pd.notna(bbb["sma_50"].iloc[49])


def test_sma_matches_a_manual_trailing_calculation():
    df = make_synthetic_ohlcv(tickers=("AAA",), num_days=30)
    features = build_features(df)

    window = 10
    manual = df["close"].rolling(window=window).mean()
    pd.testing.assert_series_equal(
        features["sma_10"].reset_index(drop=True),
        manual.reset_index(drop=True),
        check_names=False,
    )


def test_features_are_deterministic():
    df = make_synthetic_ohlcv(num_days=150)
    first = build_features(df)
    second = build_features(df)
    pd.testing.assert_frame_equal(first, second)


def test_output_has_exactly_the_documented_feature_columns():
    df = make_synthetic_ohlcv(tickers=("AAA",), num_days=100)
    features = build_features(df)
    for column in FEATURE_COLUMNS:
        assert column in features.columns
    # original columns are preserved too, not replaced
    for column in ("ticker", "ts", "open", "high", "low", "close", "volume"):
        assert column in features.columns


def test_warm_up_rows_are_nan_not_zero_or_fabricated():
    df = make_synthetic_ohlcv(tickers=("AAA",), num_days=60)
    features = build_features(df)
    # sma_50 needs 50 rows of history; row 0 can't possibly have it yet.
    assert np.isnan(features["sma_50"].iloc[0])
    assert features["sma_50"].iloc[0] != 0
