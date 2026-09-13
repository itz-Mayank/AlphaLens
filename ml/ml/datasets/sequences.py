"""Windowed sequence datasets for the LSTM/GRU track.

A sample `i` is the trailing `sequence_length` rows of features ending at
some day `t` (inclusive), with target `future_return` computed *at* `t`
(so it already looks `horizon_days` further ahead — see
`ml/targets/targets.py`). Built per ticker so no window ever spans a
ticker boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True)
class SequenceDataset:
    X: np.ndarray  # (samples, sequence_length, n_features), float32
    y: np.ndarray  # (samples,), float32 — future_return
    tickers: list[str]
    prediction_timestamps: list


def build_sequences(
    df: pd.DataFrame,
    *,
    feature_columns: tuple[str, ...],
    target_column: str,
    sequence_length: int,
) -> SequenceDataset:
    """`df` must already be feature-engineered and target-labeled, sorted
    by `(ticker, ts)`. Rows with any `NaN` among the requested columns are
    dropped *before* windowing (per ticker) — a window is only ever built
    from `sequence_length` consecutive, fully-valid rows, never from rows
    with a warm-up-period gap silently skipped over (which would let day
    `t-1`'s features sit next to day `t-40`'s in the same window).
    """
    X_list: list[np.ndarray] = []
    y_list: list[float] = []
    tickers: list[str] = []
    timestamps: list = []

    required = [*feature_columns, target_column]
    for ticker, group in df.groupby("ticker", sort=False):
        clean = group.dropna(subset=required).reset_index(drop=True)
        feature_matrix = clean[list(feature_columns)].to_numpy(dtype=np.float32)
        targets = clean[target_column].to_numpy(dtype=np.float32)
        ts_values = clean["ts"].tolist()

        for end in range(sequence_length - 1, len(clean)):
            start = end - sequence_length + 1
            X_list.append(feature_matrix[start : end + 1])
            y_list.append(targets[end])
            tickers.append(ticker)
            timestamps.append(ts_values[end])

    if not X_list:
        n_features = len(feature_columns)
        return SequenceDataset(
            X=np.empty((0, sequence_length, n_features), dtype=np.float32),
            y=np.empty((0,), dtype=np.float32),
            tickers=[],
            prediction_timestamps=[],
        )

    return SequenceDataset(
        X=np.stack(X_list),
        y=np.array(y_list, dtype=np.float32),
        tickers=tickers,
        prediction_timestamps=timestamps,
    )


class SequenceScaler:
    """Standardizes sequence features. `fit` must be called on the
    TRAINING sequence set only; `transform` is then applied to
    validation/test without refitting — this is the mechanism
    `tests/unit/test_no_leakage.py::test_scaler_fit_only_on_train` checks
    directly (fitting on train-only parameters must differ from fitting on
    the full dataset, proving isolation, not just asserting an API was
    called in the right order).
    """

    def __init__(self) -> None:
        self._scaler = StandardScaler()
        self._fitted = False

    def fit(self, X: np.ndarray) -> SequenceScaler:
        n_samples, sequence_length, n_features = X.shape
        self._scaler.fit(X.reshape(n_samples * sequence_length, n_features))
        self._fitted = True
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("SequenceScaler.transform() called before fit()")
        n_samples, sequence_length, n_features = X.shape
        flat = self._scaler.transform(X.reshape(n_samples * sequence_length, n_features))
        return flat.reshape(n_samples, sequence_length, n_features).astype(np.float32)

    @property
    def mean_(self) -> np.ndarray:
        return self._scaler.mean_

    @property
    def scale_(self) -> np.ndarray:
        return self._scaler.scale_
