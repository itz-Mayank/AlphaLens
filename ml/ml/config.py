"""Central, reproducible experiment configuration. Nothing in this package
scatters hyperparameters or magic numbers through training code — a
training run's *entire* configuration lives in one `ExperimentConfig`
instance, which gets recorded verbatim in the model registry (see
ml/registry/registry.py) so a run can be reproduced from its metadata
alone.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import numpy as np

FEATURE_SET_VERSION = "fs_v1"


def set_global_seed(seed: int) -> None:
    """Seeds every source of randomness this package uses. Call once at the
    start of any script/test that trains a model or builds a dataset with
    randomness (e.g. weight initialization) — not needed for the (fully
    deterministic) feature-engineering path."""
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


@dataclass(frozen=True)
class TargetConfig:
    """See ml/targets/targets.py and docs/ml-pipeline.md 'Target design'."""

    horizon_days: int = 5
    # Classification thresholds, in decimal return units (0.01 = 1%).
    # Computed from the TRAINING split only (never from val/test) by
    # ml.targets.targets.derive_classification_thresholds — these are the
    # *fallback* fixed values used only if a caller doesn't derive them
    # from data. Documented reasoning for the fallback: roughly the
    # 1-standard-deviation move of a 5-day return for a typical
    # large-cap equity, a round, pre-registered number rather than one
    # fit to any specific dataset.
    bearish_threshold: float = -0.02
    bullish_threshold: float = 0.02


@dataclass(frozen=True)
class SplitConfig:
    """Chronological split boundaries — see ml/datasets/temporal_split.py.
    Dates are inclusive on both ends of each split. `None` end dates mean
    "the rest of the data"."""

    train_end: str  # ISO date, e.g. "2016-06-30"
    validation_end: str  # ISO date, e.g. "2017-06-30"
    # test = everything after validation_end


@dataclass(frozen=True)
class SequenceConfig:
    """See ml/datasets/sequences.py."""

    sequence_length: int = 60


@dataclass(frozen=True)
class ExperimentConfig:
    """The full, reproducible configuration for one training run."""

    seed: int = 42
    tickers: tuple[str, ...] = (
        "AAPL",
        "MSFT",
        "AMZN",
        "GOOGL",
        "JNJ",
        "JPM",
        "FB",
        "NVDA",
        "DIS",
        "KO",
        "PG",
    )
    feature_set_version: str = FEATURE_SET_VERSION
    target: TargetConfig = field(default_factory=TargetConfig)
    split: SplitConfig = field(
        default_factory=lambda: SplitConfig(train_end="2016-06-30", validation_end="2017-06-30")
    )
    sequence: SequenceConfig = field(default_factory=SequenceConfig)

    def as_dict(self) -> dict:
        return {
            "seed": self.seed,
            "tickers": list(self.tickers),
            "feature_set_version": self.feature_set_version,
            "target": {
                "horizon_days": self.target.horizon_days,
                "bearish_threshold": self.target.bearish_threshold,
                "bullish_threshold": self.target.bullish_threshold,
            },
            "split": {
                "train_end": self.split.train_end,
                "validation_end": self.split.validation_end,
            },
            "sequence": {"sequence_length": self.sequence.sequence_length},
        }
