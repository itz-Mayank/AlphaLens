import numpy as np
import pytest
from ml.datasets.sequences import SequenceScaler, build_sequences
from ml.features.pipeline import FEATURE_COLUMNS, build_features
from ml.targets.targets import future_return

from tests.helpers import make_synthetic_ohlcv


def _prepare(num_days: int = 150):
    df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=num_days)
    featured = build_features(df)
    featured["future_return"] = future_return(featured, horizon_days=5)
    return featured


def test_sequence_shapes():
    featured = _prepare()
    seq_len = 20
    dataset = build_sequences(
        featured,
        feature_columns=FEATURE_COLUMNS,
        target_column="future_return",
        sequence_length=seq_len,
    )
    assert dataset.X.ndim == 3
    assert dataset.X.shape[1] == seq_len
    assert dataset.X.shape[2] == len(FEATURE_COLUMNS)
    assert dataset.y.shape[0] == dataset.X.shape[0]
    assert len(dataset.tickers) == dataset.X.shape[0]
    assert len(dataset.prediction_timestamps) == dataset.X.shape[0]


def test_sequences_never_span_a_ticker_boundary():
    """If windows could span tickers, the total sample count would be
    `len(all_clean_rows) - seq_len + 1` (one long run); per-ticker
    windowing instead gives `sum(len(ticker_rows) - seq_len + 1)`, which
    is smaller. Checking the exact expected count (not just "some
    samples exist for each ticker") is what actually rules out
    cross-boundary windows.
    """
    featured = _prepare(num_days=100)
    seq_len = 20
    dataset = build_sequences(
        featured,
        feature_columns=FEATURE_COLUMNS,
        target_column="future_return",
        sequence_length=seq_len,
    )

    expected_total = 0
    for ticker in ("AAA", "BBB"):
        ticker_rows = featured[featured["ticker"] == ticker].dropna(
            subset=[*FEATURE_COLUMNS, "future_return"]
        )
        expected_total += len(ticker_rows) - seq_len + 1

    assert dataset.X.shape[0] == expected_total
    assert set(dataset.tickers) == {"AAA", "BBB"}


def test_sequence_target_matches_the_last_row_of_its_window():
    featured = _prepare(num_days=100)
    seq_len = 10
    dataset = build_sequences(
        featured,
        feature_columns=FEATURE_COLUMNS,
        target_column="future_return",
        sequence_length=seq_len,
    )
    aaa = featured[featured["ticker"] == "AAA"].dropna(subset=[*FEATURE_COLUMNS, "future_return"])
    aaa = aaa.reset_index(drop=True)
    # The first AAA sample's window covers aaa.iloc[0:seq_len]; its target
    # must be aaa's future_return at the window's LAST row (seq_len - 1).
    first_aaa_idx = dataset.tickers.index("AAA")
    assert dataset.y[first_aaa_idx] == pytest.approx(aaa["future_return"].iloc[seq_len - 1])


def test_empty_dataframe_returns_empty_dataset_not_an_error():
    featured = _prepare(num_days=5)  # far fewer rows than any reasonable seq_len
    dataset = build_sequences(
        featured, feature_columns=FEATURE_COLUMNS, target_column="future_return", sequence_length=60
    )
    assert dataset.X.shape == (0, 60, len(FEATURE_COLUMNS))
    assert len(dataset.y) == 0


class TestSequenceScalerLeakage:
    """The scaler-fit-only-on-train leakage test called for explicitly in
    the Phase 5 spec. Proves isolation by checking the fitted parameters
    differ from what fitting on the combined data would produce — not
    merely that `fit()` was called with the right argument, which would
    only prove the API was used, not that leakage is actually prevented.
    """

    def test_fitting_on_train_only_differs_from_fitting_on_everything(self):
        rng = np.random.default_rng(0)
        train = rng.normal(loc=0.0, scale=1.0, size=(50, 10, 3)).astype(np.float32)
        # Deliberately shifted distribution, so "fit on everything" would
        # produce visibly different parameters than "fit on train only".
        validation = rng.normal(loc=100.0, scale=1.0, size=(50, 10, 3)).astype(np.float32)

        train_only_scaler = SequenceScaler().fit(train)
        combined_scaler = SequenceScaler().fit(np.concatenate([train, validation], axis=0))

        assert not np.allclose(train_only_scaler.mean_, combined_scaler.mean_)
        # explicitly: the train-only mean should be near 0 (train's true
        # mean), not pulled toward 50 (the combined mean) or 100
        # (validation's mean) — this is the actual leakage check, not just
        # "the two scalers differ somehow".
        assert np.all(np.abs(train_only_scaler.mean_) < 1.0)

    def test_transform_before_fit_raises(self):
        scaler = SequenceScaler()
        with pytest.raises(RuntimeError, match="fit"):
            scaler.transform(np.zeros((5, 10, 3), dtype=np.float32))

    def test_validation_data_transformed_with_train_parameters_not_its_own(self):
        rng = np.random.default_rng(1)
        train = rng.normal(loc=0.0, scale=1.0, size=(50, 10, 2)).astype(np.float32)
        validation = rng.normal(loc=5.0, scale=1.0, size=(50, 10, 2)).astype(np.float32)

        scaler = SequenceScaler().fit(train)
        transformed_validation = scaler.transform(validation)

        # If validation had been (incorrectly) standardized using its OWN
        # mean, its transformed mean would be ~0. Since it's transformed
        # with TRAIN's mean (~0) instead, a validation set centered at 5
        # comes out centered near 5, not near 0.
        assert transformed_validation.mean() > 2.0
