"""Baselines. The point of a baseline is to answer "does the ML actually
add value?" — every XGBoost/LSTM/GRU result is only meaningful relative to
these numbers, not in isolation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.models.base import Model


class NaiveZeroReturnModel(Model):
    """Always predicts a future return of exactly 0. The simplest possible
    regression baseline — if a real model can't beat this on MAE/RMSE, it
    has learned nothing useful."""

    model_type = "baseline_zero_return"

    def fit(self, X: Any, y: Any) -> None:
        pass

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(X), dtype=np.float32)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"model_type": self.model_type}))

    @classmethod
    def load(cls, path: Path) -> NaiveZeroReturnModel:
        return cls()


class PreviousReturnBaseline(Model):
    """Predicts the future h-day return as equal to the most recent
    realized 1-day return (`return_1d`) — a "persistence" / random-walk
    baseline: tomorrow (and the next h days) will look like today did."""

    model_type = "baseline_previous_return"

    def __init__(self, feature_column: str = "return_1d"):
        self.feature_column = feature_column

    def fit(self, X: Any, y: Any) -> None:
        pass

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return X[self.feature_column].to_numpy(dtype=np.float32)

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps({"model_type": self.model_type, "feature_column": self.feature_column})
        )

    @classmethod
    def load(cls, path: Path) -> PreviousReturnBaseline:
        data = json.loads(path.read_text())
        return cls(feature_column=data["feature_column"])


class MajorityClassBaseline(Model):
    """Always predicts whichever class was most frequent in the training
    labels — the baseline every classifier must beat on balanced metrics
    (accuracy alone is misleading here since classes are rarely balanced;
    see `ml/evaluation/classification.py`)."""

    model_type = "baseline_majority_class"

    def __init__(self) -> None:
        self.majority_class: str | None = None

    def fit(self, X: Any, y: pd.Series) -> None:
        self.majority_class = y.mode(dropna=True).iloc[0]

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.majority_class is None:
            raise RuntimeError("MajorityClassBaseline.predict() called before fit()")
        return np.full(len(X), self.majority_class, dtype=object)

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps({"model_type": self.model_type, "majority_class": self.majority_class})
        )

    @classmethod
    def load(cls, path: Path) -> MajorityClassBaseline:
        data = json.loads(path.read_text())
        model = cls()
        model.majority_class = data["majority_class"]
        return model
