import pandas as pd
from ml.data.validation import clean, validate

from tests.helpers import make_synthetic_ohlcv


def test_clean_synthetic_data_passes_validation():
    df = make_synthetic_ohlcv(num_days=260)
    report = validate(df, min_history_days=200)
    assert report.is_clean
    assert report.row_count == len(df)
    assert report.ticker_count == 2


def test_detects_missing_columns():
    df = make_synthetic_ohlcv().drop(columns=["volume"])
    report = validate(df)
    assert not report.is_clean
    assert "volume" in report.missing_columns


def test_detects_duplicate_timestamps():
    df = make_synthetic_ohlcv(num_days=50)
    duplicated_row = df.iloc[[0]].copy()
    df = pd.concat([df, duplicated_row]).reset_index(drop=True)
    report = validate(df, min_history_days=1)
    assert not report.is_clean
    assert len(report.duplicate_timestamps) == 1


def test_detects_out_of_order_timestamps():
    df = make_synthetic_ohlcv(num_days=50)
    aaa = df[df["ticker"] == "AAA"].copy()
    aaa.iloc[[0, 1]] = aaa.iloc[[1, 0]].to_numpy()
    other = df[df["ticker"] != "AAA"]
    report = validate(pd.concat([aaa, other]).reset_index(drop=True), min_history_days=1)
    assert not report.is_clean
    assert "AAA" in report.out_of_order


def test_detects_invalid_ohlc_relationship():
    df = make_synthetic_ohlcv(num_days=50)
    df.loc[0, "high"] = df.loc[0, "low"] - 1  # high < low: impossible
    report = validate(df, min_history_days=1)
    assert not report.is_clean
    assert len(report.invalid_ohlc_relationship) >= 1


def test_detects_non_positive_price():
    df = make_synthetic_ohlcv(num_days=50)
    df.loc[0, "close"] = 0
    report = validate(df, min_history_days=1)
    assert not report.is_clean
    assert len(report.non_positive_price) >= 1


def test_detects_negative_volume():
    df = make_synthetic_ohlcv(num_days=50)
    df.loc[0, "volume"] = -100
    report = validate(df, min_history_days=1)
    assert not report.is_clean
    assert len(report.negative_volume) >= 1


def test_detects_missing_values():
    df = make_synthetic_ohlcv(num_days=50)
    df.loc[0, "close"] = None
    report = validate(df, min_history_days=1)
    assert not report.is_clean
    assert report.missing_values["close"] == 1


def test_flags_insufficient_history_without_failing_validation():
    df = make_synthetic_ohlcv(num_days=10)
    report = validate(df, min_history_days=200)
    assert report.is_clean  # insufficient history is informational, not blocking
    assert len(report.insufficient_history) == 2


def test_suspicious_jump_is_flagged_not_blocking():
    df = make_synthetic_ohlcv(num_days=50)
    df.loc[10, "close"] = df.loc[9, "close"] * 3  # +200% in one day
    df.loc[10, "high"] = df.loc[10, "close"] * 1.01
    df.loc[10, "low"] = df.loc[9, "close"] * 0.99
    report = validate(df, min_history_days=1)
    assert report.is_clean  # flagged, not a hard failure
    assert len(report.suspicious_jumps) >= 1


def test_clean_drops_exact_duplicates_and_nothing_else():
    df = make_synthetic_ohlcv(num_days=50)
    duplicated_row = df.iloc[[5]].copy()
    with_dup = pd.concat([df, duplicated_row]).reset_index(drop=True)

    cleaned = clean(with_dup)

    assert len(cleaned) == len(df)
    pd.testing.assert_frame_equal(
        cleaned.reset_index(drop=True), df.sort_values(["ticker", "ts"]).reset_index(drop=True)
    )
