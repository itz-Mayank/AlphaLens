from ml.datasets.tabular import add_next_day_return, build_tabular_dataset
from ml.features.pipeline import FEATURE_COLUMNS, build_features
from ml.targets.targets import classify_return, future_return

from tests.helpers import make_synthetic_ohlcv


def _prepare(num_days: int = 150):
    df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=num_days)
    featured = build_features(df)
    featured["future_return"] = future_return(featured, horizon_days=5)
    featured = add_next_day_return(featured)
    featured["future_class"] = classify_return(
        featured["future_return"], bearish_threshold=-0.02, bullish_threshold=0.02
    )
    return featured


def test_build_tabular_dataset_drops_rows_with_any_nan_feature_or_target():
    featured = _prepare()
    dataset = build_tabular_dataset(featured, feature_columns=FEATURE_COLUMNS)

    assert dataset.X.isna().sum().sum() == 0
    assert dataset.y_return.isna().sum() == 0
    assert dataset.y_class.isna().sum() == 0
    assert len(dataset.X) < len(featured)  # warm-up + horizon rows were dropped


def test_build_tabular_dataset_aligned_lengths():
    featured = _prepare()
    dataset = build_tabular_dataset(featured, feature_columns=FEATURE_COLUMNS)
    n = len(dataset.X)
    assert len(dataset.y_return) == n
    assert len(dataset.y_class) == n
    assert len(dataset.tickers) == n
    assert len(dataset.timestamps) == n
    assert len(dataset.next_day_return) == n


def test_next_day_return_is_correct_at_a_split_boundary():
    """The whole reason `add_next_day_return` runs on the full series
    before splitting: a row at the very end of one split must still see
    the true next-day return, not NaN just because it's that split's last
    row."""
    featured = _prepare(num_days=150)
    aaa = featured[featured["ticker"] == "AAA"].reset_index(drop=True)
    # Pick a row comfortably before the end of AAA's series.
    idx = 100
    expected = aaa["close"].iloc[idx + 1] / aaa["close"].iloc[idx] - 1
    assert aaa["next_day_return"].iloc[idx] == expected


def test_build_tabular_dataset_requires_next_day_return_column():
    import pytest

    featured = _prepare().drop(columns=["next_day_return"])
    with pytest.raises(ValueError, match="add_next_day_return"):
        build_tabular_dataset(featured, feature_columns=FEATURE_COLUMNS)
