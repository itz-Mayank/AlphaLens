"""LSTM return-regression model. See docs/ml-pipeline.md 'LSTM vs GRU' for
the documented architecture (sequence length, hidden size, layers, dropout,
loss, optimizer, learning-rate, early stopping) — all defined once in
`ml.models._recurrent.RecurrentHyperparameters` and shared verbatim with
the GRU track so the comparison is fair (see `_recurrent.py`'s docstring).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ml.models._recurrent import RecurrentHyperparameters, RecurrentReturnModel
from ml.models.base import Model


class LSTMReturnModel(Model):
    model_type = "lstm_return"

    def __init__(self, hyperparameters: RecurrentHyperparameters | None = None):
        self._impl = RecurrentReturnModel("lstm", hyperparameters)

    @property
    def hyperparameters(self) -> RecurrentHyperparameters:
        return self._impl.hyperparameters

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        validation_data: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> list[dict]:
        return self._impl.fit(X, y, validation_data=validation_data)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self._impl.predict(X)

    def save(self, path: Path) -> None:
        self._impl.save(path)

    @classmethod
    def load(cls, path: Path) -> LSTMReturnModel:
        instance = cls()
        instance._impl = RecurrentReturnModel.load(path)
        return instance
