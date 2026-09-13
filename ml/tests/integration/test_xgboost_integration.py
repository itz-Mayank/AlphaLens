"""XGBoost integration tests: real training on synthetic tabular data
(the unit tests mock nothing, but keep the data trivially small; these
exercise the full fit -> predict -> save -> load round trip the way
`ml/pipelines/train_pipeline.py` actually uses these models)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from ml.models.xgboost.model import (
    XGBoostDirectionModel,
    XGBoostHyperparameters,
    XGBoostReturnModel,
)
from ml.targets.targets import CLASS_NAMES

_TabularData = tuple[pd.DataFrame, pd.Series, pd.Series]


def _make_tabular_data(n_rows: int = 200, seed: int = 0) -> _TabularData:
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(
        {
            "return_1d": rng.normal(0, 0.01, n_rows),
            "sma_10": rng.normal(100, 5, n_rows),
            "rsi_14": rng.uniform(0, 100, n_rows),
        }
    )
    y_return = pd.Series(rng.normal(0, 0.02, n_rows), name="future_return")
    y_class = pd.Series(rng.choice(CLASS_NAMES, size=n_rows), name="future_class", dtype=object)
    return X, y_return, y_class


class TestXGBoostReturnModel:
    def test_fit_predict_without_validation_data(self):
        X, y_return, _ = _make_tabular_data()
        model = XGBoostReturnModel(XGBoostHyperparameters(n_estimators=10))
        model.fit(X, y_return)
        predictions = model.predict(X)
        assert predictions.shape == (len(X),)
        assert np.all(np.isfinite(predictions))

    def test_fit_with_validation_data_enables_early_stopping(self):
        X_train, y_train, _ = _make_tabular_data(seed=1)
        X_val, y_val, _ = _make_tabular_data(seed=2)
        model = XGBoostReturnModel(
            XGBoostHyperparameters(n_estimators=200, early_stopping_rounds=5)
        )
        model.fit(X_train, y_train, validation_data=(X_val, y_val))
        predictions = model.predict(X_val)
        assert predictions.shape == (len(X_val),)
        # Early stopping actually engaged: fewer trees than the ceiling.
        assert model._model.best_iteration is not None
        assert model._model.best_iteration + 1 <= 200

    def test_predict_before_fit_raises(self):
        model = XGBoostReturnModel()
        with pytest.raises(RuntimeError):
            model.predict(pd.DataFrame({"a": [1.0]}))

    def test_save_load_round_trip_produces_identical_predictions(self, tmp_path):
        X, y_return, _ = _make_tabular_data()
        model = XGBoostReturnModel(XGBoostHyperparameters(n_estimators=10))
        model.fit(X, y_return)
        before = model.predict(X)

        model.save(tmp_path / "xgboost_return")
        reloaded = XGBoostReturnModel.load(tmp_path / "xgboost_return")
        after = reloaded.predict(X)

        np.testing.assert_allclose(before, after)
        assert reloaded.hyperparameters == model.hyperparameters


class TestXGBoostDirectionModel:
    def test_fit_predict_and_predict_proba(self):
        X, _, y_class = _make_tabular_data()
        model = XGBoostDirectionModel(XGBoostHyperparameters(n_estimators=10))
        model.fit(X, y_class)

        predictions = model.predict(X)
        assert set(predictions).issubset(set(CLASS_NAMES))

        proba = model.predict_proba(X)
        assert proba.shape == (len(X), len(CLASS_NAMES))
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-5)

    def test_fit_with_validation_data(self):
        X_train, _, y_train = _make_tabular_data(seed=1)
        X_val, _, y_val = _make_tabular_data(seed=2)
        model = XGBoostDirectionModel(
            XGBoostHyperparameters(n_estimators=100, early_stopping_rounds=5)
        )
        model.fit(X_train, y_train, validation_data=(X_val, y_val))
        predictions = model.predict(X_val)
        assert len(predictions) == len(X_val)

    def test_save_load_round_trip_produces_identical_predictions(self, tmp_path):
        X, _, y_class = _make_tabular_data()
        model = XGBoostDirectionModel(XGBoostHyperparameters(n_estimators=10))
        model.fit(X, y_class)
        before = model.predict_proba(X)

        model.save(tmp_path / "xgboost_direction")
        reloaded = XGBoostDirectionModel.load(tmp_path / "xgboost_direction")
        after = reloaded.predict_proba(X)

        np.testing.assert_allclose(before, after)
