"""Tests for `ml.registry.promotion` — the gate that decides whether a
trained-and-VALIDATED candidate may become PRODUCTION (servable). All
records here are hand-built (no real training) since the gate's decision
logic depends only on registry contents, not on how they got there — see
`tests/integration/test_train_pipeline_integration.py` for the real,
trained-model version of this behavior.
"""

from __future__ import annotations

import uuid

import pytest
from ml.registry.promotion import apply_promotion, evaluate_promotion
from ml.registry.registry import ModelRecord, ModelRegistry, ModelStatus, new_version_string

DATASET_VERSION = "promotion_test_v1"


def _record(
    *,
    model_type: str,
    metrics: dict,
    dataset_version: str = DATASET_VERSION,
    status: str = ModelStatus.VALIDATED,
) -> ModelRecord:
    return ModelRecord(
        model_name=model_type,
        model_type=model_type,
        version=new_version_string(model_type),
        dataset_version=dataset_version,
        feature_version="fs_v1",
        hyperparameters={},
        train_period=("2020-01-01", "2020-06-30"),
        validation_period=("2020-07-01", "2020-08-31"),
        test_period=("2020-09-01", "2020-10-31"),
        metrics=metrics,
        artifact_path=f"/nonexistent/{uuid.uuid4()}",
        created_at="2026-01-01T00:00:00Z",
        git_commit=None,
        status=status,
    )


class TestEvaluatePromotionRegressionGate:
    """`xgboost_return` vs `previous_return_baseline`, MAE, lower is better."""

    def test_a_candidate_that_beats_the_baseline_is_promoted(self, tmp_path):
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(
            _record(model_type="previous_return_baseline", metrics={"regression": {"mae": 0.02}})
        )
        candidate = _record(model_type="xgboost_return", metrics={"regression": {"mae": 0.015}})
        registry.register(candidate)

        decision = evaluate_promotion(registry, registry.get(candidate.record_id))

        assert decision.promoted is True
        assert decision.candidate_metric == 0.015
        assert decision.baseline_metric == 0.02

    def test_a_candidate_that_does_not_beat_the_baseline_is_rejected(self, tmp_path):
        """The explicit Phase 10 adversarial scenario: a candidate failing
        evaluation cannot become active."""
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(
            _record(model_type="previous_return_baseline", metrics={"regression": {"mae": 0.02}})
        )
        candidate = _record(model_type="xgboost_return", metrics={"regression": {"mae": 0.03}})
        registry.register(candidate)

        decision = evaluate_promotion(registry, registry.get(candidate.record_id))

        assert decision.promoted is False
        assert "did not beat baseline" in decision.reason.lower()

    def test_a_candidate_that_beats_baseline_but_regresses_vs_current_production_is_rejected(
        self, tmp_path
    ):
        """The explicit Phase 10 adversarial scenario: the active model
        remains active when a candidate fails (here, "fails" means
        "worse than what's already serving," not just "worse than a
        baseline")."""
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(
            _record(model_type="previous_return_baseline", metrics={"regression": {"mae": 0.03}})
        )
        current_production = _record(
            model_type="xgboost_return",
            metrics={"regression": {"mae": 0.01}},
            status=ModelStatus.PRODUCTION,
        )
        registry.register(current_production)
        candidate = _record(
            model_type="xgboost_return", metrics={"regression": {"mae": 0.02}}
        )  # beats baseline (0.03) but worse than active (0.01)
        registry.register(candidate)

        decision = evaluate_promotion(registry, registry.get(candidate.record_id))

        assert decision.promoted is False
        assert "regressed vs current production" in decision.reason.lower()

    def test_no_matching_baseline_for_dataset_version_is_rejected(self, tmp_path):
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(
            _record(
                model_type="previous_return_baseline",
                metrics={"regression": {"mae": 0.02}},
                dataset_version="a_different_dataset_v1",
            )
        )
        candidate = _record(model_type="xgboost_return", metrics={"regression": {"mae": 0.001}})
        registry.register(candidate)

        decision = evaluate_promotion(registry, registry.get(candidate.record_id))

        assert decision.promoted is False
        assert "no" in decision.reason.lower() and "baseline" in decision.reason.lower()


class TestEvaluatePromotionClassificationGate:
    """`xgboost_direction` vs `majority_class_baseline`, f1_macro, higher is better."""

    def test_a_candidate_that_beats_the_baseline_is_promoted(self, tmp_path):
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(
            _record(
                model_type="majority_class_baseline",
                metrics={"classification": {"f1_macro": 0.24}},
            )
        )
        candidate = _record(
            model_type="xgboost_direction", metrics={"classification": {"f1_macro": 0.29}}
        )
        registry.register(candidate)

        decision = evaluate_promotion(registry, registry.get(candidate.record_id))

        assert decision.promoted is True


class TestEvaluatePromotionEdgeCases:
    def test_a_model_type_with_no_gate_policy_is_never_promoted(self, tmp_path):
        registry = ModelRegistry(tmp_path / "registry.json")
        candidate = _record(model_type="some_experimental_model", metrics={})
        registry.register(candidate)

        decision = evaluate_promotion(registry, registry.get(candidate.record_id))

        assert decision.promoted is False
        assert "no promotion policy" in decision.reason.lower()

    def test_a_candidate_missing_the_required_metric_is_rejected_not_crashed(self, tmp_path):
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(
            _record(model_type="previous_return_baseline", metrics={"regression": {"mae": 0.02}})
        )
        candidate = _record(model_type="xgboost_return", metrics={})  # no regression.mae
        registry.register(candidate)

        decision = evaluate_promotion(registry, registry.get(candidate.record_id))

        assert decision.promoted is False


class TestApplyPromotionMutatesTheRegistry:
    def test_promoting_a_candidate_archives_the_previous_production_record(self, tmp_path):
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(
            _record(model_type="previous_return_baseline", metrics={"regression": {"mae": 0.03}})
        )
        old_production = _record(
            model_type="xgboost_return",
            metrics={"regression": {"mae": 0.02}},
            status=ModelStatus.PRODUCTION,
        )
        registry.register(old_production)
        candidate = _record(model_type="xgboost_return", metrics={"regression": {"mae": 0.01}})
        registry.register(candidate)

        decision = apply_promotion(registry, registry.get(candidate.record_id))

        assert decision.promoted is True
        assert registry.get(candidate.record_id)["status"] == ModelStatus.PRODUCTION
        assert registry.get(old_production.record_id)["status"] == ModelStatus.ARCHIVED
        # get_active never returns two records — the archive above is what
        # guarantees that invariant holds after a promotion.
        assert registry.get_active("xgboost_return")["record_id"] == candidate.record_id

    def test_a_rejected_candidate_is_marked_failed_and_current_production_is_untouched(
        self, tmp_path
    ):
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(
            _record(model_type="previous_return_baseline", metrics={"regression": {"mae": 0.01}})
        )
        active = _record(
            model_type="xgboost_return",
            metrics={"regression": {"mae": 0.01}},
            status=ModelStatus.PRODUCTION,
        )
        registry.register(active)
        bad_candidate = _record(model_type="xgboost_return", metrics={"regression": {"mae": 0.05}})
        registry.register(bad_candidate)

        decision = apply_promotion(registry, registry.get(bad_candidate.record_id))

        assert decision.promoted is False
        assert registry.get(bad_candidate.record_id)["status"] == ModelStatus.FAILED
        assert registry.get(active.record_id)["status"] == ModelStatus.PRODUCTION
        assert registry.get_active("xgboost_return")["record_id"] == active.record_id


class TestGetActiveInvariant:
    def test_get_active_returns_none_when_nothing_has_ever_been_promoted(self, tmp_path):
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(_record(model_type="xgboost_return", metrics={}))
        assert registry.get_active("xgboost_return") is None

    def test_get_active_raises_if_the_invariant_is_somehow_violated(self, tmp_path):
        """Promotion always archives the previous PRODUCTION record before
        setting a new one, so two simultaneous PRODUCTION records of the
        same type should never happen — if they somehow do (e.g. a manual
        registry edit), get_active refuses to silently pick one."""
        registry = ModelRegistry(tmp_path / "registry.json")
        registry.register(
            _record(model_type="xgboost_return", metrics={}, status=ModelStatus.PRODUCTION)
        )
        registry.register(
            _record(model_type="xgboost_return", metrics={}, status=ModelStatus.PRODUCTION)
        )
        with pytest.raises(RuntimeError, match="Invariant violated"):
            registry.get_active("xgboost_return")
