import numpy as np
import pytest
from ml.evaluation.regression import evaluate_regression


def test_perfect_predictions():
    y_true = np.array([0.01, -0.02, 0.03])
    metrics = evaluate_regression(y_true, y_true.copy())
    assert metrics.mae == pytest.approx(0.0, abs=1e-9)
    assert metrics.rmse == pytest.approx(0.0, abs=1e-9)
    assert metrics.r2 == pytest.approx(1.0)


def test_known_mae_and_rmse():
    y_true = np.array([1.0, 2.0, 3.0])
    y_pred = np.array([1.0, 2.0, 5.0])  # one error of 2
    metrics = evaluate_regression(y_true, y_pred)
    assert metrics.mae == pytest.approx(2 / 3)
    assert metrics.rmse == pytest.approx(np.sqrt((0 + 0 + 4) / 3))


def test_constant_predictions_produce_a_defined_but_poor_r2():
    y_true = np.array([1.0, 2.0, 3.0, 4.0])
    y_pred = np.full(4, 2.5)
    metrics = evaluate_regression(y_true, y_pred)
    assert metrics.r2 <= 0.5  # a constant predictor explains little variance


def test_empty_predictions_raise_rather_than_fabricate_a_metric():
    with pytest.raises(ValueError, match="zero samples"):
        evaluate_regression(np.array([]), np.array([]))


def test_single_sample_r2_is_nan_not_a_fabricated_number():
    """R^2 is mathematically undefined for a single sample (zero
    variance to explain) — must come back as NaN, not 0 or 1."""
    metrics = evaluate_regression(np.array([1.0]), np.array([1.5]))
    assert np.isnan(metrics.r2)
    assert metrics.mae == pytest.approx(0.5)
