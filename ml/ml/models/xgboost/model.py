"""XGBoost baseline models — the first "serious" ML in the comparison
(after the naive baselines), and the benchmark LSTM/GRU must beat to
justify the added complexity of a deep sequence model. Two thin wrappers
around `xgboost`'s sklearn API: one for the return-regression target, one
for the Bearish/Neutral/Bullish classification target — same
hyperparameter philosophy (shallow trees, a real but not-tuned learning
rate, no hyperparameter search yet — see module docstring in
`ml/pipelines/train_pipeline.py` for why).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from ml.models.base import Model
from ml.targets.targets import CLASS_NAMES


@dataclass(frozen=True)
class XGBoostHyperparameters:
    """Deliberately conservative, hand-picked defaults — not the result of
    a hyperparameter search (Phase 5's rule: establish a reproducible
    baseline first, per docs/ml-pipeline.md). `n_estimators` is a ceiling:
    when `fit(..., validation_data=...)` is used, early stopping against
    that validation set (never the test set) typically stops well short
    of it."""

    n_estimators: int = 200
    max_depth: int = 4
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    random_state: int = 42
    early_stopping_rounds: int = 20


class XGBoostReturnModel(Model):
    """Regresses `future_return` directly."""

    model_type = "xgboost_return"

    def __init__(self, hyperparameters: XGBoostHyperparameters | None = None):
        self.hyperparameters = hyperparameters or XGBoostHyperparameters()
        self._model: xgb.XGBRegressor | None = None

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        *,
        validation_data: tuple[pd.DataFrame, pd.Series] | None = None,
    ) -> None:
        """`validation_data`, if given, enables early stopping against it
        (`n_estimators` is a ceiling, not a fixed count) — never against
        the test set, which would be the same "tuning on the data you
        evaluate on" leak the split boundaries exist to prevent. XGBoost's
        sklearn API requires `early_stopping_rounds` to be a constructor
        argument matched with an `eval_set` at fit time, so the estimator
        is (re)constructed here, not in `__init__`, letting a caller
        without a validation split fit normally (no early stopping) rather
        than hitting "early stopping requires an eval_set" for free.
        """
        params = asdict(self.hyperparameters)
        early_stopping_rounds = params.pop("early_stopping_rounds")
        if validation_data is not None:
            self._model = xgb.XGBRegressor(**params, early_stopping_rounds=early_stopping_rounds)
            self._model.fit(X, y, eval_set=[validation_data], verbose=False)
        else:
            self._model = xgb.XGBRegressor(**params)
            self._model.fit(X, y)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("predict() called before fit()")
        return self._model.predict(X).astype(np.float32)

    @property
    def native_estimator(self) -> xgb.XGBRegressor:
        """The underlying `xgboost` sklearn-API estimator — for callers
        (e.g. `ml.explainability.shap_explainer`) that need direct access
        to it (SHAP's `TreeExplainer` takes the native estimator, not this
        wrapper). Prefer `predict()`/`save()`/`load()` for everything else."""
        if self._model is None:
            raise RuntimeError("native_estimator accessed before fit()")
        return self._model

    def save(self, path: Path) -> None:
        if self._model is None:
            raise RuntimeError("save() called before fit()")
        path.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path / "model.json"))
        (path / "hyperparameters.json").write_text(json.dumps(asdict(self.hyperparameters)))

    @classmethod
    def load(cls, path: Path) -> XGBoostReturnModel:
        hyperparameters = XGBoostHyperparameters(
            **json.loads((path / "hyperparameters.json").read_text())
        )
        instance = cls(hyperparameters)
        instance._model = xgb.XGBRegressor()
        instance._model.load_model(str(path / "model.json"))
        return instance


class XGBoostDirectionModel(Model):
    """Classifies into `ml.targets.targets.CLASS_NAMES`."""

    model_type = "xgboost_direction"

    def __init__(self, hyperparameters: XGBoostHyperparameters | None = None):
        self.hyperparameters = hyperparameters or XGBoostHyperparameters()
        self._model: xgb.XGBClassifier | None = None

    def _encode(self, y: pd.Series) -> np.ndarray:
        return y.map({name: i for i, name in enumerate(CLASS_NAMES)}).to_numpy()

    def _new_estimator(self, *, early_stopping_rounds: int | None) -> xgb.XGBClassifier:
        params = asdict(self.hyperparameters)
        params.pop("early_stopping_rounds")
        kwargs = {"early_stopping_rounds": early_stopping_rounds} if early_stopping_rounds else {}
        return xgb.XGBClassifier(
            **params, objective="multi:softprob", num_class=len(CLASS_NAMES), **kwargs
        )

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        *,
        validation_data: tuple[pd.DataFrame, pd.Series] | None = None,
    ) -> None:
        if validation_data is not None:
            X_val, y_val = validation_data
            self._model = self._new_estimator(
                early_stopping_rounds=self.hyperparameters.early_stopping_rounds
            )
            self._model.fit(
                X, self._encode(y), eval_set=[(X_val, self._encode(y_val))], verbose=False
            )
        else:
            self._model = self._new_estimator(early_stopping_rounds=None)
            self._model.fit(X, self._encode(y))

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("predict() called before fit()")
        encoded = self._model.predict(X)
        return np.array([CLASS_NAMES[i] for i in encoded], dtype=object)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """`(n_samples, len(CLASS_NAMES))`, columns in `CLASS_NAMES` order."""
        if self._model is None:
            raise RuntimeError("predict_proba() called before fit()")
        return self._model.predict_proba(X)

    @property
    def native_estimator(self) -> xgb.XGBClassifier:
        """See `XGBoostReturnModel.native_estimator` — the underlying
        `xgboost` estimator, for `ml.explainability.shap_explainer`."""
        if self._model is None:
            raise RuntimeError("native_estimator accessed before fit()")
        return self._model

    def save(self, path: Path) -> None:
        if self._model is None:
            raise RuntimeError("save() called before fit()")
        path.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path / "model.json"))
        (path / "hyperparameters.json").write_text(json.dumps(asdict(self.hyperparameters)))

    @classmethod
    def load(cls, path: Path) -> XGBoostDirectionModel:
        hyperparameters = XGBoostHyperparameters(
            **json.loads((path / "hyperparameters.json").read_text())
        )
        instance = cls(hyperparameters)
        instance._model = xgb.XGBClassifier()
        instance._model.load_model(str(path / "model.json"))
        return instance
