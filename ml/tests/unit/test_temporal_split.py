import pandas as pd
import pytest
from ml.config import SplitConfig
from ml.datasets.temporal_split import chronological_split

from tests.helpers import make_synthetic_ohlcv


def test_split_boundaries_are_chronological_and_non_overlapping():
    df = make_synthetic_ohlcv(tickers=("AAA",), num_days=300)
    split = SplitConfig(train_end="2020-06-30", validation_end="2020-09-30")

    train, validation, test, bounds = chronological_split(df, split)

    assert pd.to_datetime(train["ts"]).max() <= pd.Timestamp(split.train_end)
    assert pd.to_datetime(validation["ts"]).min() > pd.Timestamp(split.train_end)
    assert pd.to_datetime(validation["ts"]).max() <= pd.Timestamp(split.validation_end)
    assert pd.to_datetime(test["ts"]).min() > pd.Timestamp(split.validation_end)
    assert len(train) + len(validation) + len(test) == len(df)


def test_split_preserves_row_order_within_each_split():
    df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=300)
    split = SplitConfig(train_end="2020-06-30", validation_end="2020-09-30")
    train, _, _, _ = chronological_split(df, split)
    # still sorted by (ticker, ts) — never shuffled.
    for _ticker, group in train.groupby("ticker"):
        ts_values = list(group["ts"])
        assert ts_values == sorted(ts_values)


def test_split_never_shuffles_rows_between_tickers():
    df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=200)
    split = SplitConfig(train_end="2020-06-30", validation_end="2020-08-31")
    train, validation, test, _ = chronological_split(df, split)
    for part in (train, validation, test):
        assert set(part["ticker"].unique()) <= {"AAA", "BBB"}


def test_raises_when_train_end_is_not_before_validation_end():
    df = make_synthetic_ohlcv(num_days=100)
    split = SplitConfig(train_end="2020-06-30", validation_end="2020-03-31")
    with pytest.raises(ValueError, match="train_end"):
        chronological_split(df, split)


def test_raises_when_a_split_would_be_empty():
    df = make_synthetic_ohlcv(tickers=("AAA",), num_days=30)
    split = SplitConfig(train_end="2019-01-01", validation_end="2019-06-01")
    with pytest.raises(ValueError, match="empty"):
        chronological_split(df, split)


def test_bounds_reflect_actual_min_max_dates():
    df = make_synthetic_ohlcv(tickers=("AAA",), num_days=300)
    split = SplitConfig(train_end="2020-06-30", validation_end="2020-09-30")
    _, _, _, bounds = chronological_split(df, split)
    assert bounds.train_start == pd.to_datetime(df["ts"]).min().date()
    assert bounds.test_end == pd.to_datetime(df["ts"]).max().date()
