"""End-to-end smoke test for `ml.pipelines.train_pipeline.run_experiment` —
the whole research -> validation -> features -> targets -> split ->
baselines -> XGBoost -> LSTM/GRU -> evaluation -> registry -> structured
output chain, wired together the same way a real run would use it.

Uses small, deterministic SYNTHETIC data (`tests/helpers.make_synthetic_ohlcv`)
injected via a throwaway `ResearchDataProvider`, not `SampleSP500ResearchProvider`
— this test is about the pipeline's plumbing being correct and fast to run
in CI, not about producing a real performance number. The real-data run
(`ml/data/sample_data/research_sample_sp500.csv`) is a separate, explicit
experiment script — see docs/ml-pipeline.md — never conflated with this
test's synthetic fixture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import pytest
from ml.config import ExperimentConfig, SequenceConfig, SplitConfig
from ml.data.contracts import DataEnvironment, DatasetProvenance
from ml.data.research_provider import ResearchDataProvider
from ml.pipelines.train_pipeline import run_experiment

from tests.helpers import make_synthetic_ohlcv

EXPECTED_REGRESSION_MODELS = (
    "naive_zero_return",
    "previous_return_baseline",
    "xgboost_return",
    "lstm_return",
    "gru_return",
)
EXPECTED_CLASSIFICATION_MODELS = ("majority_class_baseline", "xgboost_direction")


class _SyntheticResearchProvider(ResearchDataProvider):
    """A throwaway provider wrapping `make_synthetic_ohlcv`'s output. Marked
    `DataEnvironment.DEMO` in its own provenance (not `RESEARCH`) precisely
    because it is fabricated data being pushed through the research
    pipeline for test speed — mislabeling it `RESEARCH` would blur exactly
    the environments Phase 5 requires kept separate."""

    def __init__(self, df: pd.DataFrame):
        self._df = df

    def load(self, tickers=None) -> tuple[pd.DataFrame, DatasetProvenance]:
        df = self._df
        if tickers is not None:
            df = df[df["ticker"].isin(tickers)]
        df = df.reset_index(drop=True)
        provenance = DatasetProvenance(
            source="tests.helpers.make_synthetic_ohlcv (fabricated, deterministic)",
            environment=DataEnvironment.DEMO,
            tickers=tuple(sorted(df["ticker"].unique())),
            start_date=df["ts"].min(),
            end_date=df["ts"].max(),
            retrieved_at=datetime.now(UTC),
            dataset_version="synthetic_pipeline_smoke_test_v1",
            notes="Integration-test fixture only — never used for a performance claim.",
        )
        return df, provenance


@pytest.fixture(scope="module")
def experiment_result(tmp_path_factory):
    df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=500, start="2020-01-01", seed=7)
    dates = sorted(df["ts"].unique())
    train_end = dates[int(0.6 * len(dates))]
    validation_end = dates[int(0.8 * len(dates))]

    config = ExperimentConfig(
        seed=42,
        tickers=("AAA", "BBB"),
        split=SplitConfig(
            train_end=train_end.isoformat(), validation_end=validation_end.isoformat()
        ),
        sequence=SequenceConfig(sequence_length=10),
    )
    output_dir = tmp_path_factory.mktemp("experiment") / "run_001"
    provider = _SyntheticResearchProvider(df)
    return run_experiment(config, output_dir, provider=provider)


class TestRunExperimentSmoke:
    def test_all_expected_models_are_present(self, experiment_result):
        models = experiment_result.metrics["models"]
        for name in (*EXPECTED_REGRESSION_MODELS, *EXPECTED_CLASSIFICATION_MODELS):
            assert name in models, f"missing model '{name}' in experiment metrics"

    def test_regression_models_have_regression_and_financial_metrics(self, experiment_result):
        models = experiment_result.metrics["models"]
        for name in EXPECTED_REGRESSION_MODELS:
            entry = models[name]
            assert "regression" in entry
            assert "financial" in entry
            reg = entry["regression"]
            assert reg["mae"] >= 0
            assert reg["rmse"] >= 0

            financial = entry["financial"]
            assert "per_ticker" in financial
            assert "aggregate" in financial
            assert set(financial["per_ticker"]) == {"AAA", "BBB"}
            assert financial["aggregate"]["num_tickers_evaluated"] == 2

    def test_classification_models_have_classification_metrics(self, experiment_result):
        models = experiment_result.metrics["models"]
        for name in EXPECTED_CLASSIFICATION_MODELS:
            clf = models[name]["classification"]
            assert 0.0 <= clf["accuracy"] <= 1.0
            assert len(clf["confusion_matrix"]) == 3  # Bearish/Neutral/Bullish

    def test_split_bounds_are_chronological_with_no_overlap(self, experiment_result):
        bounds = experiment_result.split_bounds
        assert bounds.train_start <= bounds.train_end < bounds.validation_start
        assert bounds.validation_start <= bounds.validation_end < bounds.test_start
        assert bounds.test_start <= bounds.test_end

    def test_structured_output_files_are_written(self, experiment_result):
        output_dir = experiment_result.output_dir
        for filename in (
            "configuration.json",
            "provenance.json",
            "metrics.json",
            "split_bounds.json",
        ):
            path = output_dir / filename
            assert path.exists(), f"missing structured output file: {filename}"
            json.loads(path.read_text())  # must be valid JSON

    def test_model_artifacts_are_saved_to_disk(self, experiment_result):
        models_dir = experiment_result.output_dir / "models"
        for name in ("xgboost_return", "xgboost_direction", "lstm_return", "gru_return"):
            assert (models_dir / name).exists(), f"missing artifact directory for '{name}'"
            assert any((models_dir / name).iterdir()), f"artifact directory for '{name}' is empty"

    def test_every_trained_model_is_registered(self, experiment_result):
        registry_path = experiment_result.output_dir.parent / "registry.json"
        assert registry_path.exists()
        records = json.loads(registry_path.read_text())
        registered_names = {record["model_name"] for record in records}
        for name in (*EXPECTED_REGRESSION_MODELS, *EXPECTED_CLASSIFICATION_MODELS):
            assert name in registered_names

    def test_provenance_reflects_the_injected_synthetic_provider_not_the_real_dataset(
        self, experiment_result
    ):
        provenance = experiment_result.provenance
        assert provenance.environment == DataEnvironment.DEMO
        assert "fabricated" in provenance.source.lower()
        assert provenance.dataset_version == "synthetic_pipeline_smoke_test_v1"


class TestPromotionGateRunsAutomatically:
    """Phase 10: training succeeding must never be the same thing as being
    servable — every model_type with a promotion policy must end this run
    at PRODUCTION or FAILED, never left sitting at VALIDATED."""

    def test_gated_model_types_end_at_production_or_failed_never_validated(self, experiment_result):
        registry_path = experiment_result.output_dir.parent / "registry.json"
        records = json.loads(registry_path.read_text())
        gated_types = {"xgboost_return", "xgboost_direction", "lstm_return", "gru_return"}
        for record in records:
            if record["model_type"] in gated_types:
                assert record["status"] in ("PRODUCTION", "FAILED"), (
                    f"{record['model_type']} ({record['record_id']}) is still "
                    f"{record['status']!r} after the promotion gate should have run"
                )
                assert record["status_reason"], "a gated decision must always record why"

    def test_baselines_are_never_touched_by_the_promotion_gate(self, experiment_result):
        registry_path = experiment_result.output_dir.parent / "registry.json"
        records = json.loads(registry_path.read_text())
        baseline_types = {
            "naive_zero_return",
            "previous_return_baseline",
            "majority_class_baseline",
        }
        for record in records:
            if record["model_type"] in baseline_types:
                assert record["status"] == "VALIDATED"
                assert record["status_reason"] is None

    def test_gated_records_have_a_real_artifact_checksum(self, experiment_result):
        registry_path = experiment_result.output_dir.parent / "registry.json"
        records = json.loads(registry_path.read_text())
        for record in records:
            if record["model_type"] in {"xgboost_return", "xgboost_direction"}:
                assert record["artifact_checksum"] is not None
                assert len(record["artifact_checksum"]) == 64  # sha256 hex digest

    def test_promotion_decisions_file_is_written_and_matches_the_registry(self, experiment_result):
        decisions_path = experiment_result.output_dir / "promotion_decisions.json"
        assert decisions_path.exists()
        decisions = json.loads(decisions_path.read_text())
        registry_path = experiment_result.output_dir.parent / "registry.json"
        records = {r["model_type"]: r for r in json.loads(registry_path.read_text())}
        for model_type, decision in decisions.items():
            expected_status = "PRODUCTION" if decision["promoted"] else "FAILED"
            assert records[model_type]["status"] == expected_status

    def test_a_promoted_model_is_actually_loadable_via_get_active(self, experiment_result):
        """The real point of all of this: `ml.inference.serving` only
        loads PRODUCTION models, so a promoted candidate must actually be
        resolvable that way, using this run's real (not synthetic-stub)
        artifacts."""
        from ml.registry.registry import ModelRegistry

        registry_path = experiment_result.output_dir.parent / "registry.json"
        registry = ModelRegistry(registry_path)
        return_active = registry.get_active("xgboost_return")
        direction_active = registry.get_active("xgboost_direction")
        # Given this fixture's synthetic data, both are expected to beat
        # their (also freshly-computed, same-dataset) baselines — but if
        # they didn't, asserting a hardcoded "must be promoted" here would
        # be exactly the kind of arbitrary pass-forcing this gate exists
        # to prevent. Assert the *consistency* property instead: whichever
        # way the gate decided, get_active must agree with it.
        registry_path_records = json.loads(registry_path.read_text())
        for model_type, active in (
            ("xgboost_return", return_active),
            ("xgboost_direction", direction_active),
        ):
            production_records = [
                r
                for r in registry_path_records
                if r["model_type"] == model_type and r["status"] == "PRODUCTION"
            ]
            if production_records:
                assert active is not None
                assert active["record_id"] == production_records[0]["record_id"]
            else:
                assert active is None
