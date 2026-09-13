"""SHAP explainability for the XGBoost models — prioritized because XGBoost
is the strongest-performing model from Phase 5 (see docs/ml-pipeline.md
"Real experiment results"), and `shap.TreeExplainer` is exact and fast for
tree ensembles (no sampling/approximation needed, unlike a model-agnostic
explainer).

**SHAP explains the contribution of features to a model's prediction; it
does not establish causality.** A feature with a large positive SHAP value
moved *this model's output* in the positive direction relative to the
model's average prediction — that is a statement about the model's learned
behavior on this input, not a claim about what actually drives the
security's future return. Every function here returns "contribution", never
"cause" or "reason", and this module is never wired to imply otherwise.

Still standalone `ml/` code — no FastAPI import. `backend/app/services/`
is the only thing that calls into this module (ADR-001), and only from a
dedicated, separately-requested endpoint — never computed as a side effect
of an ordinary forecast request (SHAP is materially more expensive than a
plain `predict()` call).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap

from ml.models.xgboost.model import XGBoostDirectionModel, XGBoostReturnModel


@dataclass(frozen=True)
class FeatureContribution:
    feature: str
    value: float
    contribution: float
    direction: str  # "positive" | "negative"

    def as_dict(self) -> dict:
        return {
            "feature": self.feature,
            "value": self.value,
            "contribution": self.contribution,
            "direction": self.direction,
        }


def _rank_top_n(
    feature_row: pd.Series, shap_row: np.ndarray, feature_columns: tuple[str, ...], top_n: int
) -> list[FeatureContribution]:
    contributions = [
        FeatureContribution(
            feature=name,
            value=float(feature_row[name]),
            contribution=float(shap_value),
            direction="positive" if shap_value >= 0 else "negative",
        )
        for name, shap_value in zip(feature_columns, shap_row, strict=True)
    ]
    # Ranked by magnitude — the features that moved this prediction the
    # most in either direction, not just the positive ones.
    contributions.sort(key=lambda c: abs(c.contribution), reverse=True)
    return contributions[:top_n]


def explain_return_prediction(
    model: XGBoostReturnModel,
    feature_row: pd.Series,
    feature_columns: tuple[str, ...],
    *,
    top_n: int = 5,
) -> list[FeatureContribution]:
    """Top-`top_n` features (by `abs(contribution)`) behind one
    `XGBoostReturnModel` prediction, for the single row `feature_row`
    (indexed by feature name, e.g. one row of `ml.features.pipeline.build_features`'s
    output)."""
    X = pd.DataFrame([feature_row[list(feature_columns)].to_dict()])
    explainer = shap.TreeExplainer(model.native_estimator)
    shap_values = explainer.shap_values(X)
    return _rank_top_n(feature_row, shap_values[0], feature_columns, top_n)


def explain_direction_prediction(
    model: XGBoostDirectionModel,
    feature_row: pd.Series,
    feature_columns: tuple[str, ...],
    *,
    predicted_class_index: int,
    top_n: int = 5,
) -> list[FeatureContribution]:
    """Top-`top_n` features behind one `XGBoostDirectionModel` prediction,
    explained relative to the model's **predicted class specifically**
    (`predicted_class_index` into `ml.targets.targets.CLASS_NAMES`) — the
    question a "why did the model predict Bullish" UI actually asks, not a
    three-way breakdown across all classes at once."""
    X = pd.DataFrame([feature_row[list(feature_columns)].to_dict()])
    explainer = shap.TreeExplainer(model.native_estimator)
    shap_values = explainer.shap_values(X)
    # This SHAP/xgboost version returns (n_samples, n_features, n_classes)
    # for a multiclass `XGBClassifier`.
    class_shap_row = shap_values[0, :, predicted_class_index]
    return _rank_top_n(feature_row, class_shap_row, feature_columns, top_n)
