"""End-to-end orchestration: research data -> validation -> features ->
targets -> temporal split -> baseline/XGBoost/LSTM/GRU -> evaluation ->
registry -> structured experiment output on disk.

Hyperparameters here are intentionally modest (small trees, a small
recurrent hidden size, a capped epoch budget with early stopping) — Phase
5's goal is a reproducible, leakage-free pipeline and an honest model
comparison, not chasing a benchmark number. See docs/ml-pipeline.md for the
full methodology this function implements.

This module imports `ml.models.xgboost`/`ml.models.lstm`/`ml.models.gru`
and orchestrates training — it is never imported by, or run inside,
`backend/`. Training never executes inside an HTTP request; see
docs/decisions.md ADR-001 and docs/ml-pipeline.md 'Training vs inference'.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ml.config import ExperimentConfig, set_global_seed
from ml.data import validation
from ml.data.contracts import DatasetProvenance
from ml.data.research_provider import ResearchDataProvider, SampleSP500ResearchProvider
from ml.datasets.sequences import build_sequences
from ml.datasets.tabular import add_next_day_return, build_tabular_dataset
from ml.datasets.temporal_split import TemporalSplitBounds, chronological_split
from ml.evaluation.classification import evaluate_classification
from ml.evaluation.financial import evaluate_strategy_per_ticker
from ml.evaluation.regression import evaluate_regression
from ml.features.pipeline import FEATURE_COLUMNS, build_features
from ml.models.baseline.naive import (
    MajorityClassBaseline,
    NaiveZeroReturnModel,
    PreviousReturnBaseline,
)
from ml.models.gru.model import GRUReturnModel
from ml.models.lstm.model import LSTMReturnModel
from ml.models.xgboost.model import XGBoostDirectionModel, XGBoostReturnModel
from ml.registry.promotion import GATE_POLICY, apply_promotion
from ml.registry.registry import (
    ModelRecord,
    ModelRegistry,
    ModelStatus,
    compute_artifact_checksum,
    get_git_commit,
    new_version_string,
)
from ml.targets.targets import classify_return, derive_classification_thresholds, future_return


@dataclass
class ExperimentResult:
    output_dir: Path
    provenance: DatasetProvenance
    split_bounds: TemporalSplitBounds
    metrics: dict


def _prepare_dataset(
    config: ExperimentConfig, provider: ResearchDataProvider
) -> tuple[pd.DataFrame, DatasetProvenance, TemporalSplitBounds]:
    raw, provenance = provider.load(config.tickers)

    report = validation.validate(raw, min_history_days=200)
    if not report.is_clean:
        raise ValueError(f"Research data failed validation:\n{report.summary()}")
    clean = validation.clean(raw)

    featured = build_features(clean)
    featured["future_return"] = future_return(featured, config.target.horizon_days)
    featured = add_next_day_return(featured)

    train_df, _, _, _ = chronological_split(featured, config.split)
    bearish, bullish = derive_classification_thresholds(train_df["future_return"])
    featured["future_class"] = classify_return(
        featured["future_return"], bearish_threshold=bearish, bullish_threshold=bullish
    )

    train_df, validation_df, test_df, bounds = chronological_split(featured, config.split)
    combined = pd.concat(
        [
            train_df.assign(_split="train"),
            validation_df.assign(_split="validation"),
            test_df.assign(_split="test"),
        ]
    ).reset_index(drop=True)
    combined.attrs["thresholds"] = {"bearish": bearish, "bullish": bullish}
    return combined, provenance, bounds


def run_experiment(
    config: ExperimentConfig,
    output_dir: Path,
    *,
    provider: ResearchDataProvider | None = None,
) -> ExperimentResult:
    set_global_seed(config.seed)
    provider = provider or SampleSP500ResearchProvider()
    output_dir.mkdir(parents=True, exist_ok=True)

    combined, provenance, bounds = _prepare_dataset(config, provider)
    thresholds = combined.attrs["thresholds"]

    train_df = combined[combined["_split"] == "train"]
    validation_df = combined[combined["_split"] == "validation"]
    test_df = combined[combined["_split"] == "test"]

    train_tab = build_tabular_dataset(train_df, feature_columns=FEATURE_COLUMNS)
    validation_tab = build_tabular_dataset(validation_df, feature_columns=FEATURE_COLUMNS)
    test_tab = build_tabular_dataset(test_df, feature_columns=FEATURE_COLUMNS)

    metrics: dict = {"thresholds": thresholds, "models": {}}

    def _record_regression(
        model_name: str,
        model,
        X_test,
        y_test_return: pd.Series,
        tickers: pd.Series,
        next_day_returns: pd.Series,
    ) -> None:
        predictions = model.predict(X_test)
        reg_metrics = evaluate_regression(y_test_return.to_numpy(), predictions)
        # Per-ticker, never a naive cross-ticker concatenation — see
        # `evaluate_strategy_per_ticker`'s docstring for why that would be
        # a real correctness bug (trades/compounding spanning ticker
        # boundaries), not just a modeling simplification.
        financial = evaluate_strategy_per_ticker(
            tickers=tickers, forecasts=predictions, actual_next_day_returns=next_day_returns
        )
        metrics["models"][model_name] = {
            "regression": reg_metrics.as_dict(),
            "financial": financial,
        }

    # --- Baselines ---
    zero_model = NaiveZeroReturnModel()
    _record_regression(
        "naive_zero_return",
        zero_model,
        test_tab.X,
        test_tab.y_return,
        test_tab.tickers,
        test_tab.next_day_return,
    )

    prev_return_model = PreviousReturnBaseline()
    _record_regression(
        "previous_return_baseline",
        prev_return_model,
        test_tab.X,
        test_tab.y_return,
        test_tab.tickers,
        test_tab.next_day_return,
    )

    majority_model = MajorityClassBaseline()
    majority_model.fit(train_tab.X, train_tab.y_class)
    majority_predictions = majority_model.predict(test_tab.X)
    metrics["models"]["majority_class_baseline"] = {
        "classification": evaluate_classification(
            test_tab.y_class.to_numpy(), majority_predictions
        ).as_dict()
    }

    # --- XGBoost ---
    xgb_return_model = XGBoostReturnModel()
    xgb_return_model.fit(
        train_tab.X, train_tab.y_return, validation_data=(validation_tab.X, validation_tab.y_return)
    )
    _record_regression(
        "xgboost_return",
        xgb_return_model,
        test_tab.X,
        test_tab.y_return,
        test_tab.tickers,
        test_tab.next_day_return,
    )
    xgb_return_model.save(output_dir / "models" / "xgboost_return")

    xgb_direction_model = XGBoostDirectionModel()
    xgb_direction_model.fit(
        train_tab.X, train_tab.y_class, validation_data=(validation_tab.X, validation_tab.y_class)
    )
    xgb_direction_predictions = xgb_direction_model.predict(test_tab.X)
    xgb_direction_proba = xgb_direction_model.predict_proba(test_tab.X)
    metrics["models"]["xgboost_direction"] = {
        "classification": evaluate_classification(
            test_tab.y_class.to_numpy(), xgb_direction_predictions, xgb_direction_proba
        ).as_dict()
    }
    xgb_direction_model.save(output_dir / "models" / "xgboost_direction")

    # --- LSTM / GRU (sequence models) ---
    train_seq = build_sequences(
        train_df,
        feature_columns=FEATURE_COLUMNS,
        target_column="future_return",
        sequence_length=config.sequence.sequence_length,
    )
    validation_seq = build_sequences(
        validation_df,
        feature_columns=FEATURE_COLUMNS,
        target_column="future_return",
        sequence_length=config.sequence.sequence_length,
    )
    test_seq = build_sequences(
        test_df,
        feature_columns=FEATURE_COLUMNS,
        target_column="future_return",
        sequence_length=config.sequence.sequence_length,
    )

    # Sequence samples are keyed by (ticker, prediction_timestamp), not a
    # shared row index like the tabular dataset — look up each sample's
    # real next-day return from the same full-series column tabular
    # datasets use, so LSTM/GRU get the identical financial-evaluation
    # treatment as the baselines/XGBoost.
    next_day_lookup = combined.set_index(["ticker", "ts"])["next_day_return"]
    test_seq_next_day_returns = pd.Series(
        [
            next_day_lookup.get((ticker, ts), float("nan"))
            for ticker, ts in zip(test_seq.tickers, test_seq.prediction_timestamps, strict=True)
        ]
    )

    for name, model_cls in (("lstm_return", LSTMReturnModel), ("gru_return", GRUReturnModel)):
        model = model_cls()
        history = model.fit(
            train_seq.X, train_seq.y, validation_data=(validation_seq.X, validation_seq.y)
        )
        predictions = model.predict(test_seq.X)
        reg_metrics = evaluate_regression(test_seq.y, predictions)
        # Per-ticker — see the identical note in `_record_regression`.
        financial = evaluate_strategy_per_ticker(
            tickers=test_seq.tickers,
            forecasts=predictions,
            actual_next_day_returns=test_seq_next_day_returns,
        )
        metrics["models"][name] = {
            "regression": reg_metrics.as_dict(),
            "financial": financial,
            "training_epochs_run": len(history),
        }
        model.save(output_dir / "models" / name)

    # --- Structured experiment output ---
    (output_dir / "configuration.json").write_text(json.dumps(config.as_dict(), indent=2))
    (output_dir / "provenance.json").write_text(json.dumps(provenance.as_dict(), indent=2))
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    (output_dir / "split_bounds.json").write_text(
        json.dumps(
            {
                "train_start": bounds.train_start.isoformat(),
                "train_end": bounds.train_end.isoformat(),
                "validation_start": bounds.validation_start.isoformat(),
                "validation_end": bounds.validation_end.isoformat(),
                "test_start": bounds.test_start.isoformat(),
                "test_end": bounds.test_end.isoformat(),
            },
            indent=2,
        )
    )

    registry = ModelRegistry(output_dir.parent / "registry.json")
    git_commit = get_git_commit()
    registered_ids: dict[str, str] = {}
    for model_name, model_metrics in metrics["models"].items():
        artifact_path = output_dir / "models" / model_name
        record = ModelRecord(
            model_name=model_name,
            model_type=model_name,
            version=new_version_string(model_name),
            dataset_version=provenance.dataset_version,
            feature_version=config.feature_set_version,
            hyperparameters=config.as_dict(),
            train_period=(bounds.train_start.isoformat(), bounds.train_end.isoformat()),
            validation_period=(
                bounds.validation_start.isoformat(),
                bounds.validation_end.isoformat(),
            ),
            test_period=(bounds.test_start.isoformat(), bounds.test_end.isoformat()),
            metrics=model_metrics,
            artifact_path=str(artifact_path),
            created_at=datetime.now(UTC).isoformat(),
            git_commit=git_commit,
            status=ModelStatus.VALIDATED,
            artifact_checksum=compute_artifact_checksum(artifact_path),
        )
        registry.register(record)
        registered_ids[model_name] = record.record_id

    # Promotion gate (Phase 10, ml.registry.promotion): training succeeding
    # and being registered as VALIDATED never implies servable — every
    # candidate with a defined gate policy is evaluated against its
    # baseline and the current PRODUCTION model (if any) right here, so a
    # freshly-trained-but-worse model can never silently become active.
    # Baselines and any model_type with no policy stay at VALIDATED
    # (`evaluate_promotion`'s "no policy defined" path is never reached
    # for them because they're simply not looked up here).
    promotion_decisions = {}
    for model_name, record_id in registered_ids.items():
        if model_name not in GATE_POLICY:
            continue
        candidate = registry.get(record_id)
        assert candidate is not None
        promotion_decisions[model_name] = apply_promotion(registry, candidate)

    (output_dir / "promotion_decisions.json").write_text(
        json.dumps({k: v.as_dict() for k, v in promotion_decisions.items()}, indent=2)
    )

    return ExperimentResult(
        output_dir=output_dir, provenance=provenance, split_bounds=bounds, metrics=metrics
    )
