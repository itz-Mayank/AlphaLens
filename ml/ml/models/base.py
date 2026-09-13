"""The common interface every model in `ml/models/` implements, so
`ml/pipelines/train_pipeline.py` and `ml/evaluation/` can treat a naive
baseline, an XGBoost model, an LSTM, and a GRU identically."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np


class Model(ABC):
    model_type: str = "base"

    @abstractmethod
    def fit(self, X: Any, y: Any) -> None: ...

    @abstractmethod
    def predict(self, X: Any) -> np.ndarray: ...

    @abstractmethod
    def save(self, path: Path) -> None: ...

    @classmethod
    @abstractmethod
    def load(cls, path: Path) -> Model: ...
