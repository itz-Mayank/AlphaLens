import numpy as np
import pytest
from ml.evaluation.classification import evaluate_classification


def test_perfect_predictions_score_perfectly():
    y_true = np.array(["Bullish", "Bearish", "Neutral", "Bullish"])
    metrics = evaluate_classification(y_true, y_true.copy())
    assert metrics.accuracy == 1.0
    assert metrics.precision_macro == 1.0
    assert metrics.recall_macro == 1.0
    assert metrics.f1_macro == 1.0


def test_known_confusion_matrix():
    y_true = np.array(["Bullish", "Bullish", "Bearish", "Bearish"])
    y_pred = np.array(["Bullish", "Bearish", "Bearish", "Bearish"])
    metrics = evaluate_classification(y_true, y_pred)
    # accuracy: 3/4 correct
    assert metrics.accuracy == pytest.approx(0.75)
    assert metrics.class_names == ("Bearish", "Neutral", "Bullish")
    # confusion_matrix rows/cols follow class_names order: Bearish, Neutral, Bullish
    cm = metrics.confusion_matrix
    assert sum(sum(row) for row in cm) == 4


def test_roc_auc_and_pr_auc_none_when_no_probabilities_given():
    y_true = np.array(["Bullish", "Bearish"])
    y_pred = np.array(["Bullish", "Bearish"])
    metrics = evaluate_classification(y_true, y_pred, y_proba=None)
    assert metrics.roc_auc_ovr is None
    assert metrics.pr_auc_macro is None


def test_roc_auc_computed_when_probabilities_given():
    y_true = np.array(["Bearish", "Neutral", "Bullish", "Bearish", "Neutral", "Bullish"])
    y_pred = y_true.copy()
    # perfect-confidence probabilities matching the true class
    class_index = {"Bearish": 0, "Neutral": 1, "Bullish": 2}
    y_proba = np.zeros((6, 3))
    for i, label in enumerate(y_true):
        y_proba[i, class_index[label]] = 1.0

    metrics = evaluate_classification(y_true, y_pred, y_proba)
    assert metrics.roc_auc_ovr == pytest.approx(1.0)
    assert metrics.pr_auc_macro == pytest.approx(1.0)


def test_empty_predictions_are_handled_by_the_caller_not_this_function():
    """sklearn's metrics raise on empty input; this module doesn't paper
    over that with a fabricated zero — callers must not call it with zero
    rows (verified: it raises, not silently returns a fake metric)."""
    with pytest.raises(ValueError):
        evaluate_classification(np.array([]), np.array([]))


def test_constant_predictions_are_scored_honestly_not_specially():
    y_true = np.array(["Bullish", "Bearish", "Neutral"])
    y_pred = np.array(["Bullish", "Bullish", "Bullish"])
    metrics = evaluate_classification(y_true, y_pred)
    assert metrics.accuracy == pytest.approx(1 / 3)
    assert metrics.recall_macro < 1.0
