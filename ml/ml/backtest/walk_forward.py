"""Walk-forward evaluation: the interfaces, plus one deterministic,
actually-executed example.

    Train window -> Validation -> Test window -> Advance window -> Retrain
    -> Next test window

Each `WalkForwardWindow` is exactly one iteration of that loop — its own
train/validation/test boundaries, built the same
`ml.datasets.temporal_split.chronological_split`-compatible way the
single-split pipeline (`ml.pipelines.train_pipeline`) already uses, just
repeated across a rolling series of non-overlapping test periods instead
of one fixed split.

Scope, stated plainly: this module implements the framework
(`generate_rolling_windows`) and ONE actually-executed walk-forward
experiment (`run_xgboost_return_walk_forward`, restricted to the XGBoost
return model because it is fast enough to retrain per-window within this
phase's scope). It is not a complete multi-model, multi-window walk-forward
study — see docs/ml-pipeline.md "Known limitations" for exactly what that
would still require (LSTM/GRU and the direction model are not walked
forward here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from ml.config import SplitConfig, TargetConfig
from ml.data import validation
from ml.data.research_provider import ResearchDataProvider
from ml.datasets.tabular import add_next_day_return, build_tabular_dataset
from ml.datasets.temporal_split import chronological_split
from ml.evaluation.regression import RegressionMetrics, evaluate_regression
from ml.features.pipeline import FEATURE_COLUMNS, build_features
from ml.models.xgboost.model import XGBoostHyperparameters, XGBoostReturnModel
from ml.targets.targets import classify_return, future_return


@dataclass(frozen=True)
class WalkForwardWindow:
    window_index: int
    train_end: date
    validation_end: date
    test_end: date


def generate_rolling_windows(
    *,
    start_date: date,
    end_date: date,
    train_days: int,
    validation_days: int,
    test_days: int,
    step_days: int,
) -> list[WalkForwardWindow]:
    """Pure, deterministic window generation — no data access, no
    training, no randomness. Window 0's `train_end` is
    `start_date + train_days`; each later window's boundaries advance by
    `step_days`. Stops once a window's `test_end` would exceed `end_date`
    (a partial trailing window is never silently included)."""
    if train_days <= 0 or validation_days <= 0 or test_days <= 0 or step_days <= 0:
        raise ValueError("train_days, validation_days, test_days, and step_days must all be > 0")

    windows: list[WalkForwardWindow] = []
    train_end = start_date + timedelta(days=train_days)
    index = 0
    while True:
        validation_end = train_end + timedelta(days=validation_days)
        test_end = validation_end + timedelta(days=test_days)
        if test_end > end_date:
            break
        windows.append(
            WalkForwardWindow(
                window_index=index,
                train_end=train_end,
                validation_end=validation_end,
                test_end=test_end,
            )
        )
        train_end = train_end + timedelta(days=step_days)
        index += 1
    return windows


@dataclass(frozen=True)
class WalkForwardWindowResult:
    window: WalkForwardWindow
    test_metrics: RegressionMetrics
    num_test_rows: int

    def as_dict(self) -> dict:
        return {
            "window_index": self.window.window_index,
            "train_end": self.window.train_end.isoformat(),
            "validation_end": self.window.validation_end.isoformat(),
            "test_end": self.window.test_end.isoformat(),
            "num_test_rows": self.num_test_rows,
            "test_metrics": {
                "mae": self.test_metrics.mae,
                "rmse": self.test_metrics.rmse,
                "r2": self.test_metrics.r2,
            },
        }


def run_xgboost_return_walk_forward(
    provider: ResearchDataProvider,
    *,
    tickers: tuple[str, ...],
    windows: list[WalkForwardWindow],
    horizon_days: int = 5,
    hyperparameters: XGBoostHyperparameters | None = None,
) -> list[WalkForwardWindowResult]:
    """Retrains a FRESH `XGBoostReturnModel` from scratch for every window
    (never reusing a previous window's fitted model — each window's model
    only ever sees that window's own train/validation rows), then scores
    it on that window's own held-out test period. Every window's data is
    still validated (`ml.data.validation.validate`) and features are built
    with the exact same `ml.features.pipeline.build_features` training
    uses — no separate walk-forward-specific feature logic.
    """
    raw, _ = provider.load(tickers)
    report = validation.validate(raw, min_history_days=200)
    if not report.is_clean:
        raise ValueError(f"Research data failed validation:\n{report.summary()}")
    clean = validation.clean(raw)
    featured = build_features(clean)
    featured["future_return"] = future_return(featured, horizon_days=horizon_days)
    featured = add_next_day_return(featured)
    # `build_tabular_dataset` requires a classification label column too
    # (it serves both the regression and classification tracks) — this
    # walk-forward experiment only scores the *regression* model, so the
    # class label is otherwise unused here. Using `TargetConfig`'s fixed,
    # pre-registered fallback thresholds (never derived from any window's
    # own data) rather than deriving per-window thresholds keeps this
    # placeholder column leakage-free by construction, since it doesn't
    # feed into anything this function actually evaluates.
    fallback = TargetConfig()
    featured["future_class"] = classify_return(
        featured["future_return"],
        bearish_threshold=fallback.bearish_threshold,
        bullish_threshold=fallback.bullish_threshold,
    )
    ts = pd.to_datetime(featured["ts"])

    results: list[WalkForwardWindowResult] = []
    for window in windows:
        split = SplitConfig(
            train_end=window.train_end.isoformat(),
            validation_end=window.validation_end.isoformat(),
        )
        # Bound this window's "test" data to its own test_end — otherwise
        # `chronological_split`'s test split (everything after
        # validation_end) would include every later window's data too.
        window_slice = featured[ts <= pd.Timestamp(window.test_end)]
        train_df, validation_df, test_df, _ = chronological_split(window_slice, split)

        train_tab = build_tabular_dataset(train_df, feature_columns=FEATURE_COLUMNS)
        validation_tab = build_tabular_dataset(validation_df, feature_columns=FEATURE_COLUMNS)
        test_tab = build_tabular_dataset(test_df, feature_columns=FEATURE_COLUMNS)

        model = XGBoostReturnModel(hyperparameters or XGBoostHyperparameters())
        model.fit(
            train_tab.X,
            train_tab.y_return,
            validation_data=(validation_tab.X, validation_tab.y_return),
        )
        predictions = model.predict(test_tab.X)
        metrics = evaluate_regression(test_tab.y_return.to_numpy(), predictions)

        results.append(
            WalkForwardWindowResult(
                window=window, test_metrics=metrics, num_test_rows=len(test_tab.X)
            )
        )

    return results
