"""Shared infrastructure for the LSTM and GRU tracks. Both
`ml/models/lstm/model.py` and `ml/models/gru/model.py` are thin wrappers
around `_RecurrentNet` differing *only* in `cell_type` — every other line
(training loop, scaling, early stopping, serialization) is identical, so a
performance difference between them reflects the recurrent cell, not
incidental implementation differences. This is what makes "LSTM vs GRU"
in docs/ml-pipeline.md a fair comparison rather than an apples-to-oranges
one.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import torch
from torch import nn

from ml.datasets.sequences import SequenceScaler


@dataclass(frozen=True)
class RecurrentHyperparameters:
    """Deliberately small — see module docstring in
    `ml/pipelines/train_pipeline.py` on not benchmark-chasing."""

    hidden_size: int = 32
    num_layers: int = 1
    dropout: float = 0.2
    learning_rate: float = 1e-3
    max_epochs: int = 30
    batch_size: int = 64
    early_stopping_patience: int = 5
    random_state: int = 42


class _RecurrentNet(nn.Module):
    def __init__(
        self,
        cell_type: Literal["lstm", "gru"],
        input_size: int,
        hidden_size: int,
        num_layers: int,
        dropout: float,
    ):
        super().__init__()
        rnn_cls = nn.LSTM if cell_type == "lstm" else nn.GRU
        self.rnn = rnn_cls(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.head = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output, _ = self.rnn(x)
        last_step = output[:, -1, :]  # the final time step's hidden state
        return self.head(last_step).squeeze(-1)


class RecurrentReturnModel:
    """Not a `ml.models.base.Model` subclass directly — `LSTMReturnModel`
    and `GRUReturnModel` are (see their `model.py`), each pinning
    `cell_type`. Kept as a plain class here (not ABC-registered) since it
    always needs `cell_type` supplied by its caller.
    """

    def __init__(
        self,
        cell_type: Literal["lstm", "gru"],
        hyperparameters: RecurrentHyperparameters | None = None,
    ):
        self.cell_type = cell_type
        self.hyperparameters = hyperparameters or RecurrentHyperparameters()
        self._net: _RecurrentNet | None = None
        self._scaler: SequenceScaler | None = None
        self._input_size: int | None = None

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        validation_data: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> list[dict]:
        """`X`: `(samples, sequence_length, n_features)`, raw (unscaled) —
        scaling is fit here, on `X` only, never on `validation_data`.
        Returns the per-epoch training history (train/validation loss),
        recorded rather than only printed, for the experiment output
        (`ml/pipelines/train_pipeline.py`).
        """
        torch.manual_seed(self.hyperparameters.random_state)

        self._scaler = SequenceScaler().fit(X)
        X_scaled = self._scaler.transform(X)
        self._input_size = X.shape[2]

        self._net = _RecurrentNet(
            cell_type=self.cell_type,
            input_size=self._input_size,
            hidden_size=self.hyperparameters.hidden_size,
            num_layers=self.hyperparameters.num_layers,
            dropout=self.hyperparameters.dropout,
        )
        optimizer = torch.optim.Adam(self._net.parameters(), lr=self.hyperparameters.learning_rate)
        loss_fn = nn.MSELoss()

        X_tensor = torch.from_numpy(X_scaled)
        y_tensor = torch.from_numpy(y.astype(np.float32))

        val_tensors = None
        if validation_data is not None:
            X_val_raw, y_val = validation_data
            X_val_scaled = self._scaler.transform(X_val_raw)
            val_tensors = (
                torch.from_numpy(X_val_scaled),
                torch.from_numpy(y_val.astype(np.float32)),
            )

        history: list[dict] = []
        best_val_loss = float("inf")
        best_state = None
        epochs_without_improvement = 0
        n_samples = X_tensor.shape[0]
        generator = torch.Generator().manual_seed(self.hyperparameters.random_state)

        for epoch in range(self.hyperparameters.max_epochs):
            self._net.train()
            permutation = torch.randperm(n_samples, generator=generator)
            epoch_loss = 0.0
            for start in range(0, n_samples, self.hyperparameters.batch_size):
                batch_idx = permutation[start : start + self.hyperparameters.batch_size]
                optimizer.zero_grad()
                predictions = self._net(X_tensor[batch_idx])
                loss = loss_fn(predictions, y_tensor[batch_idx])
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item() * len(batch_idx)
            train_loss = epoch_loss / n_samples

            val_loss = None
            if val_tensors is not None:
                self._net.eval()
                with torch.no_grad():
                    val_predictions = self._net(val_tensors[0])
                    val_loss = loss_fn(val_predictions, val_tensors[1]).item()

                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_state = {k: v.clone() for k, v in self._net.state_dict().items()}
                    epochs_without_improvement = 0
                else:
                    epochs_without_improvement += 1

            history.append({"epoch": epoch, "train_loss": train_loss, "validation_loss": val_loss})

            if (
                val_tensors is not None
                and epochs_without_improvement >= self.hyperparameters.early_stopping_patience
            ):
                break

        if best_state is not None:
            self._net.load_state_dict(best_state)

        return history

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._net is None or self._scaler is None:
            raise RuntimeError("predict() called before fit()")
        self._net.eval()
        X_scaled = self._scaler.transform(X)
        with torch.no_grad():
            predictions = self._net(torch.from_numpy(X_scaled))
        return predictions.numpy().astype(np.float32)

    def save(self, path: Path) -> None:
        if self._net is None or self._scaler is None:
            raise RuntimeError("save() called before fit()")
        path.mkdir(parents=True, exist_ok=True)
        torch.save(self._net.state_dict(), path / "weights.pt")
        np.savez(path / "scaler.npz", mean=self._scaler.mean_, scale=self._scaler.scale_)
        (path / "config.json").write_text(
            json.dumps(
                {
                    "cell_type": self.cell_type,
                    "input_size": self._input_size,
                    "hyperparameters": asdict(self.hyperparameters),
                }
            )
        )

    @classmethod
    def load(cls, path: Path) -> RecurrentReturnModel:
        config = json.loads((path / "config.json").read_text())
        hyperparameters = RecurrentHyperparameters(**config["hyperparameters"])
        instance = cls(cell_type=config["cell_type"], hyperparameters=hyperparameters)
        instance._input_size = config["input_size"]

        instance._net = _RecurrentNet(
            cell_type=instance.cell_type,
            input_size=instance._input_size,
            hidden_size=hyperparameters.hidden_size,
            num_layers=hyperparameters.num_layers,
            dropout=hyperparameters.dropout,
        )
        instance._net.load_state_dict(torch.load(path / "weights.pt", weights_only=True))
        instance._net.eval()

        scaler_data = np.load(path / "scaler.npz")
        scaler = SequenceScaler()
        scaler._scaler.mean_ = scaler_data["mean"]
        scaler._scaler.scale_ = scaler_data["scale"]
        scaler._scaler.n_features_in_ = len(scaler_data["mean"])
        scaler._fitted = True
        instance._scaler = scaler

        return instance
