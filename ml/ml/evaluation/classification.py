"""Classification metrics for the direction (Bearish/Neutral/Bullish)
target. Thin wrappers around scikit-learn — the value here is fixing the
class ordering/averaging choices once, not reimplementing metrics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from ml.targets.targets import CLASS_NAMES


@dataclass(frozen=True)
class ClassificationMetrics:
    accuracy: float
    precision_macro: float
    recall_macro: float
    f1_macro: float
    roc_auc_ovr: float | None
    pr_auc_macro: float | None
    confusion_matrix: list[list[int]]
    class_names: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "accuracy": self.accuracy,
            "precision_macro": self.precision_macro,
            "recall_macro": self.recall_macro,
            "f1_macro": self.f1_macro,
            "roc_auc_ovr": self.roc_auc_ovr,
            "pr_auc_macro": self.pr_auc_macro,
            "confusion_matrix": self.confusion_matrix,
            "class_names": list(self.class_names),
        }


def evaluate_classification(
    y_true: np.ndarray, y_pred: np.ndarray, y_proba: np.ndarray | None = None
) -> ClassificationMetrics:
    """`y_true`/`y_pred` are class-name strings (from `CLASS_NAMES`).
    `y_proba`, if given, is `(n_samples, len(CLASS_NAMES))` in
    `CLASS_NAMES` order — needed for ROC-AUC/PR-AUC, which a baseline that
    only emits hard labels (e.g. `MajorityClassBaseline`) can't provide;
    those two fields are `None` in that case rather than a fabricated
    value.
    """
    if len(y_true) == 0:
        raise ValueError("evaluate_classification() called with zero samples")

    roc_auc = None
    pr_auc = None
    if y_proba is not None and len(set(y_true)) > 1:
        y_true_encoded = np.array([CLASS_NAMES.index(label) for label in y_true])
        try:
            roc_auc = float(
                roc_auc_score(
                    y_true_encoded, y_proba, multi_class="ovr", labels=list(range(len(CLASS_NAMES)))
                )
            )
        except ValueError:
            roc_auc = None
        pr_scores = []
        for i in range(len(CLASS_NAMES)):
            binary_true = (y_true_encoded == i).astype(int)
            if binary_true.sum() == 0:
                continue
            pr_scores.append(average_precision_score(binary_true, y_proba[:, i]))
        pr_auc = float(np.mean(pr_scores)) if pr_scores else None

    return ClassificationMetrics(
        accuracy=float(accuracy_score(y_true, y_pred)),
        precision_macro=float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        recall_macro=float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        f1_macro=float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        roc_auc_ovr=roc_auc,
        pr_auc_macro=pr_auc,
        confusion_matrix=confusion_matrix(y_true, y_pred, labels=list(CLASS_NAMES)).tolist(),
        class_names=CLASS_NAMES,
    )
