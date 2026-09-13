"""GRU return-regression model — structurally identical to
`ml.models.lstm.LSTMReturnModel` except for the recurrent cell (see
`ml/models/_recurrent.py`'s docstring on why that's deliberate)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ml.models._recurrent import RecurrentHyperparameters, RecurrentReturnModel
from ml.models.base import Model


class GRUReturnModel(Model):
    model_type = "gru_return"

    def __init__(self, hyperparameters: RecurrentHyperparameters | None = None):
        self._impl = RecurrentReturnModel("gru", hyperparameters)

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
    def load(cls, path: Path) -> GRUReturnModel:
        instance = cls()
        instance._impl = RecurrentReturnModel.load(path)
        return instance
