"""Tests for `ml.inference.serving` — the raw-OHLCV-history -> registered-
model -> `ForecastResult` orchestration layer. Uses a small, real (not
mocked) registry + trained XGBoost artifacts built from synthetic data, so
these exercise the actual save/load/predict round trip, not a stand-in.

`_register_tiny_xgboost_models` registers both models as `PRODUCTION`
directly (bypassing `ml.registry.promotion`) — these fixtures represent
"the model currently being served," which is exactly what serving now
requires (Phase 10's promotion gate: see `ml.inference.serving`'s
docstring); going through the real promotion gate for every serving test
would mean also registering matching baselines in every test, which tests
elsewhere already cover.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from ml.datasets.tabular import add_next_day_return, build_tabular_dataset
from ml.features.pipeline import FEATURE_COLUMNS, FEATURE_SET_VERSION, build_features
from ml.inference.serving import (
    DataValidationFailedError,
    InsufficientHistoryError,
    ModelUnavailableError,
    UnsupportedTickerError,
    build_latest_feature_row,
    generate_forecast,
    generate_historical_predictions,
    load_forecast_models,
)
from ml.models.xgboost.model import (
    XGBoostDirectionModel,
    XGBoostHyperparameters,
    XGBoostReturnModel,
)
from ml.registry.registry import ModelRecord, ModelRegistry, ModelStatus, new_version_string
from ml.targets.targets import classify_return, derive_classification_thresholds, future_return

from tests.helpers import make_synthetic_ohlcv

TICKERS = ("AAA", "BBB")
DATASET_VERSION = "synthetic_serving_test_v1"


def _register_tiny_xgboost_models(
    registry_path: Path, *, feature_version: str = FEATURE_SET_VERSION
) -> None:
    """Builds a tiny real (not mocked) return + direction XGBoost pair from
    synthetic data and registers them — enough rows for the 50-row `sma_50`
    warm-up plus a handful of labeled training rows."""
    df = make_synthetic_ohlcv(tickers=TICKERS, num_days=120, seed=3)
    featured = build_features(df)
    featured["future_return"] = future_return(featured, horizon_days=5)
    bearish, bullish = derive_classification_thresholds(featured["future_return"])
    featured["future_class"] = classify_return(
        featured["future_return"], bearish_threshold=bearish, bullish_threshold=bullish
    )
    featured = add_next_day_return(featured)
    tab = build_tabular_dataset(featured, feature_columns=FEATURE_COLUMNS)

    return_model = XGBoostReturnModel(XGBoostHyperparameters(n_estimators=5))
    return_model.fit(tab.X, tab.y_return)
    direction_model = XGBoostDirectionModel(XGBoostHyperparameters(n_estimators=5))
    direction_model.fit(tab.X, tab.y_class)

    artifacts_dir = registry_path.parent / "models"
    return_model.save(artifacts_dir / "xgboost_return")
    direction_model.save(artifacts_dir / "xgboost_direction")

    registry = ModelRegistry(registry_path)
    hyperparameters = {"tickers": list(TICKERS), "target": {"horizon_days": 5}}
    registry.register(
        ModelRecord(
            model_name="xgboost_return",
            model_type="xgboost_return",
            version=new_version_string("xgboost_return"),
            dataset_version=DATASET_VERSION,
            feature_version=feature_version,
            hyperparameters=hyperparameters,
            train_period=("2020-01-01", "2020-03-01"),
            validation_period=("2020-03-02", "2020-03-15"),
            test_period=("2020-03-16", "2020-04-01"),
            metrics={"regression": {"mae": 0.02}},
            artifact_path=str(artifacts_dir / "xgboost_return"),
            created_at="2026-09-11T00:00:00Z",
            git_commit=None,
            status=ModelStatus.PRODUCTION,
        )
    )
    registry.register(
        ModelRecord(
            model_name="xgboost_direction",
            model_type="xgboost_direction",
            version=new_version_string("xgboost_direction"),
            dataset_version=DATASET_VERSION,
            feature_version=feature_version,
            hyperparameters=hyperparameters,
            train_period=("2020-01-01", "2020-03-01"),
            validation_period=("2020-03-02", "2020-03-15"),
            test_period=("2020-03-16", "2020-04-01"),
            metrics={"classification": {"f1_macro": 0.4}},
            artifact_path=str(artifacts_dir / "xgboost_direction"),
            created_at="2026-09-11T00:00:00Z",
            git_commit=None,
            status=ModelStatus.PRODUCTION,
        )
    )


class TestLoadForecastModels:
    def test_missing_registry_raises_model_unavailable(self, tmp_path):
        with pytest.raises(ModelUnavailableError):
            load_forecast_models(tmp_path / "does_not_exist" / "registry.json")

    def test_empty_registry_raises_model_unavailable(self, tmp_path):
        registry_path = tmp_path / "registry.json"
        ModelRegistry(registry_path)  # creates an empty registry, no records
        with pytest.raises(ModelUnavailableError):
            load_forecast_models(registry_path)

    def test_loads_real_trained_artifacts(self, tmp_path):
        registry_path = tmp_path / "registry.json"
        _register_tiny_xgboost_models(registry_path)

        models = load_forecast_models(registry_path)

        assert models.supported_tickers == TICKERS
        assert models.horizon_days == 5
        assert models.dataset_version == DATASET_VERSION
        # Real, loaded, usable model objects — not stand-ins.
        assert isinstance(models.return_model, XGBoostReturnModel)
        assert isinstance(models.direction_model, XGBoostDirectionModel)

    def test_mismatched_feature_versions_raise_model_unavailable(self, tmp_path):
        """`get_active` returns at most one PRODUCTION record per
        model_type by construction (promotion archives whatever it
        replaces) — so the mismatch scenario here is simulated by editing
        the ALREADY-PRODUCTION direction record's own feature_version in
        place, not by registering a competing second PRODUCTION record
        (which `ModelRegistry.get_active` would correctly refuse to
        resolve at all — see its docstring)."""
        registry_path = tmp_path / "registry.json"
        _register_tiny_xgboost_models(registry_path, feature_version="fs_v1")

        records = json.loads(registry_path.read_text())
        for record in records:
            if record["model_type"] == "xgboost_direction":
                record["feature_version"] = "fs_v2_never_trained_with_return_model"
        registry_path.write_text(json.dumps(records))

        with pytest.raises(ModelUnavailableError, match="feature version"):
            load_forecast_models(registry_path)


class TestBuildLatestFeatureRow:
    def test_raises_on_too_few_rows(self):
        df = make_synthetic_ohlcv(tickers=("AAA",), num_days=10)
        with pytest.raises(InsufficientHistoryError) as exc_info:
            build_latest_feature_row(df, min_history_rows=60)
        assert exc_info.value.available_rows == 10
        assert exc_info.value.required_rows == 60

    def test_returns_a_fully_warmed_up_row_for_enough_history(self):
        df = make_synthetic_ohlcv(tickers=("AAA",), num_days=80)
        row = build_latest_feature_row(df, min_history_rows=60)
        assert not row[list(FEATURE_COLUMNS)].isna().any()
        assert row["ts"] == df["ts"].iloc[-1]

    def test_a_second_tickers_short_history_appended_at_the_end_is_caught(self):
        """If a caller accidentally passes a multi-ticker frame instead of
        one ticker's own history, the *last* row's own warm-up (not the
        frame's total row count) is what must be sufficient — this proves
        the per-ticker feature warm-up check actually guards against that
        misuse rather than being satisfied by an unrelated ticker's rows."""
        aaa = make_synthetic_ohlcv(tickers=("AAA",), num_days=90, seed=1)
        bbb = make_synthetic_ohlcv(tickers=("BBB",), num_days=5, seed=2)
        combined = pd.concat([aaa, bbb]).reset_index(drop=True)

        with pytest.raises(InsufficientHistoryError):
            build_latest_feature_row(combined, min_history_rows=60)

    def test_invalid_ohlc_relationship_raises_data_validation_failed(self):
        df = make_synthetic_ohlcv(tickers=("AAA",), num_days=80)
        df.loc[df.index[-1], "high"] = df["low"].iloc[-1] - 1  # high < low: invalid
        with pytest.raises(DataValidationFailedError):
            build_latest_feature_row(df, min_history_rows=60)


class TestGenerateForecast:
    @pytest.fixture()
    def models(self, tmp_path):
        registry_path = tmp_path / "registry.json"
        _register_tiny_xgboost_models(registry_path)
        return load_forecast_models(registry_path)

    def test_generates_a_real_forecast_for_a_supported_ticker(self, models):
        df = make_synthetic_ohlcv(tickers=("AAA",), num_days=80, seed=5)
        result = generate_forecast(df, models, ticker="AAA")

        assert result.ticker == "AAA"
        assert result.horizon_days == 5
        assert result.dataset_version == DATASET_VERSION
        assert result.return_prediction.expected_return is not None
        assert result.direction_prediction.predicted_class in {"Bearish", "Neutral", "Bullish"}
        assert result.direction_prediction.class_probabilities is not None
        assert set(result.direction_prediction.class_probabilities) == {
            "Bearish",
            "Neutral",
            "Bullish",
        }
        probs = result.direction_prediction.class_probabilities.values()
        assert pytest.approx(sum(probs), abs=1e-5) == 1.0

    def test_unsupported_ticker_raises(self, models):
        df = make_synthetic_ohlcv(tickers=("ZZZ",), num_days=80, seed=5)
        with pytest.raises(UnsupportedTickerError) as exc_info:
            generate_forecast(df, models, ticker="ZZZ")
        assert exc_info.value.ticker == "ZZZ"
        assert exc_info.value.supported_tickers == TICKERS

    def test_insufficient_history_propagates(self, models):
        df = make_synthetic_ohlcv(tickers=("AAA",), num_days=10, seed=5)
        with pytest.raises(InsufficientHistoryError):
            generate_forecast(df, models, ticker="AAA")

    def test_predictions_are_deterministic_for_the_same_input(self, models):
        df = make_synthetic_ohlcv(tickers=("AAA",), num_days=80, seed=5)
        first = generate_forecast(df, models, ticker="AAA")
        second = generate_forecast(df, models, ticker="AAA")
        assert first.return_prediction.expected_return == second.return_prediction.expected_return
        assert (
            first.direction_prediction.predicted_class
            == second.direction_prediction.predicted_class
        )


class TestGenerateHistoricalPredictions:
    @pytest.fixture()
    def models(self, tmp_path):
        registry_path = tmp_path / "registry.json"
        _register_tiny_xgboost_models(registry_path)
        return load_forecast_models(registry_path)

    def test_produces_one_row_per_fully_warmed_up_day_per_ticker(self, models):
        df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=80, seed=6)
        predictions = generate_historical_predictions(df, models)

        assert set(predictions["ticker"]) == {"AAA", "BBB"}
        # Warm-up (longest window, sma_50) costs the first 49 rows of each
        # ticker's own history.
        assert len(predictions[predictions["ticker"] == "AAA"]) == 80 - 49
        assert len(predictions[predictions["ticker"] == "BBB"]) == 80 - 49

    def test_matches_a_single_day_forecast_for_the_same_date(self, models):
        """The batch path and the single-day `generate_forecast` path must
        agree exactly on an overlapping day — same model, same feature
        pipeline, same inputs."""
        df = make_synthetic_ohlcv(tickers=("AAA",), num_days=80, seed=7)
        historical = generate_historical_predictions(df, models)
        single = generate_forecast(df, models, ticker="AAA")

        last_row = historical[historical["ts"] == df["ts"].iloc[-1]].iloc[0]
        assert last_row["expected_return"] == pytest.approx(
            single.return_prediction.expected_return
        )
        assert last_row["predicted_class"] == single.direction_prediction.predicted_class

    def test_excludes_tickers_outside_the_trained_universe(self, models):
        df = make_synthetic_ohlcv(tickers=("AAA", "ZZZ"), num_days=80, seed=8)
        predictions = generate_historical_predictions(df, models)
        assert set(predictions["ticker"]) == {"AAA"}

    def test_raises_when_no_ticker_is_in_the_trained_universe(self, models):
        df = make_synthetic_ohlcv(tickers=("ZZZ",), num_days=80, seed=9)
        with pytest.raises(UnsupportedTickerError):
            generate_historical_predictions(df, models)

    def test_empty_input_raises_insufficient_history_not_a_key_error(self, models):
        empty = pd.DataFrame(columns=["ticker", "ts", "open", "high", "low", "close", "volume"])
        with pytest.raises(InsufficientHistoryError):
            generate_historical_predictions(empty, models)

    def test_output_has_no_future_information_truncation_invariant(self, models):
        """Truncating the tail of the input must not change any earlier
        day's prediction — the same no-lookahead guarantee
        `build_features` already proves, now checked through the batch
        scoring path end to end."""
        full = make_synthetic_ohlcv(tickers=("AAA",), num_days=100, seed=10)
        cutoff_ts = sorted(full["ts"].unique())[79]
        truncated = full[full["ts"] <= cutoff_ts]

        full_predictions = generate_historical_predictions(full, models).set_index("ts")
        truncated_predictions = generate_historical_predictions(truncated, models).set_index("ts")

        common_index = truncated_predictions.index
        pd.testing.assert_series_equal(
            full_predictions.loc[common_index, "expected_return"],
            truncated_predictions.loc[common_index, "expected_return"],
        )
        pd.testing.assert_series_equal(
            full_predictions.loc[common_index, "predicted_class"],
            truncated_predictions.loc[common_index, "predicted_class"],
        )
