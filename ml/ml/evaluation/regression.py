"""Regression metrics for the future-return target."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


@dataclass(frozen=True)
class RegressionMetrics:
    mae: float
    rmse: float
    r2: float

    def as_dict(self) -> dict:
        return {"mae": self.mae, "rmse": self.rmse, "r2": self.r2}


def evaluate_regression(y_true: np.ndarray, y_pred: np.ndarray) -> RegressionMetrics:
    if len(y_true) == 0:
        raise ValueError("evaluate_regression() called with zero samples")
    mse = mean_squared_error(y_true, y_pred)
    return RegressionMetrics(
        mae=float(mean_absolute_error(y_true, y_pred)),
        rmse=float(np.sqrt(mse)),
        r2=float(r2_score(y_true, y_pred)) if len(y_true) > 1 else float("nan"),
    )
