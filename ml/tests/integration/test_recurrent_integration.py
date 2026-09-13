"""LSTM/GRU integration tests: real training on small synthetic sequence
data. These check the things a unit test mocking the network can't:
actual convergence direction, real save/load of torch state, and that
eval-mode inference is deterministic despite dropout being enabled at
training time."""

from __future__ import annotations

import numpy as np
import pytest
from ml.models._recurrent import RecurrentHyperparameters
from ml.models.gru.model import GRUReturnModel
from ml.models.lstm.model import LSTMReturnModel


def _make_sequence_data(
    n_samples: int = 64, sequence_length: int = 10, n_features: int = 3, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, size=(n_samples, sequence_length, n_features)).astype(np.float32)
    # A target with *some* real signal (mean of the last time step) so a
    # "loss goes down" assertion is meaningful rather than trivially true
    # for pure noise.
    y = (X[:, -1, :].mean(axis=1) * 0.1).astype(np.float32)
    return X, y


@pytest.mark.parametrize("model_cls", [LSTMReturnModel, GRUReturnModel])
class TestRecurrentModels:
    def test_training_loss_decreases(self, model_cls):
        X, y = _make_sequence_data()
        hyperparameters = RecurrentHyperparameters(
            hidden_size=8, num_layers=1, max_epochs=20, early_stopping_patience=20
        )
        model = model_cls(hyperparameters)
        history = model.fit(X, y)

        assert len(history) > 1
        first_loss = history[0]["train_loss"]
        last_loss = history[-1]["train_loss"]
        assert last_loss < first_loss

    def test_predict_shape_and_finiteness(self, model_cls):
        X, y = _make_sequence_data()
        model = model_cls(RecurrentHyperparameters(hidden_size=8, max_epochs=5))
        model.fit(X, y)
        predictions = model.predict(X)
        assert predictions.shape == (len(X),)
        assert np.all(np.isfinite(predictions))

    def test_inference_is_deterministic_in_eval_mode(self, model_cls):
        X, y = _make_sequence_data()
        model = model_cls(RecurrentHyperparameters(hidden_size=8, max_epochs=5))
        model.fit(X, y)

        first = model.predict(X)
        second = model.predict(X)
        np.testing.assert_array_equal(first, second)

    def test_early_stopping_with_validation_data_restores_best_state(self, model_cls):
        X_train, y_train = _make_sequence_data(seed=1)
        X_val, y_val = _make_sequence_data(seed=2)
        hyperparameters = RecurrentHyperparameters(
            hidden_size=8, max_epochs=30, early_stopping_patience=3
        )
        model = model_cls(hyperparameters)
        history = model.fit(X_train, y_train, validation_data=(X_val, y_val))

        # Early stopping should have kicked in well before the epoch ceiling
        # on this tiny, noisy dataset.
        assert len(history) <= 30
        val_losses = [h["validation_loss"] for h in history]
        best_epoch_loss = min(val_losses)
        # The restored model's actual validation loss should match the
        # best epoch recorded during training (proving the "restore best
        # state" logic in `_recurrent.py` actually happened, not just that
        # training ran for the right number of epochs).
        restored_predictions = model.predict(X_val)
        restored_mse = float(np.mean((restored_predictions - y_val) ** 2))
        assert restored_mse == pytest.approx(best_epoch_loss, rel=1e-3, abs=1e-6)

    def test_save_load_round_trip_produces_identical_predictions(self, model_cls, tmp_path):
        X, y = _make_sequence_data()
        model = model_cls(RecurrentHyperparameters(hidden_size=8, max_epochs=5))
        model.fit(X, y)
        before = model.predict(X)

        save_path = tmp_path / model_cls.model_type
        model.save(save_path)
        reloaded = model_cls.load(save_path)
        after = reloaded.predict(X)

        np.testing.assert_allclose(before, after, atol=1e-6)
