"""The model promotion gate — Phase 10's fix for a real, pre-existing gap:
`ml.inference.serving.load_forecast_models` used to call
`ModelRegistry.best_by_metric` with no status filter at all, so a model
became eligible to be served the instant it was registered as `VALIDATED`
(which `ml.pipelines.train_pipeline` does for every model it trains,
unconditionally). "Training succeeded" and "should be served" were the
same condition — which is exactly the anti-pattern this module exists to
close: a model must not become active merely because training succeeded.

**Policy**: a candidate is promoted to `PRODUCTION` only if it (a) beats
the best registered baseline of the matching type on the SAME
`dataset_version` (apples-to-apples — comparing against a baseline
computed on different data proves nothing), and (b) does not regress
against whatever is currently `PRODUCTION` for that `model_type`, if
anything is. Every candidate that runs through `apply_promotion` ends up
at exactly `PRODUCTION` or `FAILED` — never left sitting at `VALIDATED`
forever, so serving's "must be PRODUCTION" rule always has a clear record
to find (or a clear, actionable "nothing is promoted yet" absence).

This is deliberately NOT a profitability threshold or an arbitrary metric
cutoff invented to make training runs "pass" — it is model-vs-baseline and
model-vs-current-production comparison only, using metrics the training
pipeline already computes. A model that is genuinely worse than a naive
baseline is correctly rejected, not promoted anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

from ml.registry.registry import ModelRegistry, ModelStatus

# model_type -> (baseline model_type it must beat, metric_path into the
# record dict, higher_is_better). Only model types with an entry here are
# eligible for promotion at all — see `evaluate_promotion`'s handling of a
# missing policy.
GATE_POLICY: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "xgboost_return": (
        "previous_return_baseline",
        ("metrics", "regression", "mae"),
        False,
    ),
    "xgboost_direction": (
        "majority_class_baseline",
        ("metrics", "classification", "f1_macro"),
        True,
    ),
    "lstm_return": (
        "previous_return_baseline",
        ("metrics", "regression", "mae"),
        False,
    ),
    "gru_return": (
        "previous_return_baseline",
        ("metrics", "regression", "mae"),
        False,
    ),
}


@dataclass(frozen=True)
class PromotionDecision:
    record_id: str
    model_type: str
    promoted: bool
    reason: str
    candidate_metric: float | None
    baseline_metric: float | None
    previous_production_metric: float | None

    def as_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "model_type": self.model_type,
            "promoted": self.promoted,
            "reason": self.reason,
            "candidate_metric": self.candidate_metric,
            "baseline_metric": self.baseline_metric,
            "previous_production_metric": self.previous_production_metric,
        }


def _extract_metric(record: dict, metric_path: tuple[str, ...]) -> float | None:
    value: dict | float | None = record
    for key in metric_path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value if isinstance(value, int | float) else None


def _rejected(candidate: dict, reason: str) -> PromotionDecision:
    return PromotionDecision(
        record_id=candidate["record_id"],
        model_type=candidate["model_type"],
        promoted=False,
        reason=reason,
        candidate_metric=None,
        baseline_metric=None,
        previous_production_metric=None,
    )


def evaluate_promotion(registry: ModelRegistry, candidate: dict) -> PromotionDecision:
    """Pure decision logic — reads the registry, never writes to it (see
    `apply_promotion` for the mutating counterpart). Split out so the
    policy itself is directly unit-testable against a hand-built registry
    without needing to also verify the write side each time."""
    model_type = candidate["model_type"]
    policy = GATE_POLICY.get(model_type)
    if policy is None:
        return _rejected(
            candidate,
            f"No promotion policy is defined for model_type={model_type!r} — "
            "not eligible for PRODUCTION (see promotion.GATE_POLICY).",
        )
    baseline_type, metric_path, higher_is_better = policy
    metric_name = ".".join(metric_path)

    candidate_metric = _extract_metric(candidate, metric_path)
    if candidate_metric is None:
        return _rejected(candidate, f"Candidate record has no {metric_name} metric to evaluate.")

    # Same dataset_version only — a baseline scored on different data is
    # not a valid comparison, regardless of how good its number looks.
    baseline_scored = [
        (r, _extract_metric(r, metric_path))
        for r in registry.list_all()
        if r["model_type"] == baseline_type and r["dataset_version"] == candidate["dataset_version"]
    ]
    baseline_scored = [(r, v) for r, v in baseline_scored if v is not None]
    if not baseline_scored:
        return _rejected(
            candidate,
            f"No {baseline_type!r} baseline record found for "
            f"dataset_version={candidate['dataset_version']!r} to compare against.",
        )
    _baseline_record, baseline_metric = (
        max(baseline_scored, key=lambda rv: rv[1])
        if higher_is_better
        else min(baseline_scored, key=lambda rv: rv[1])
    )

    beats_baseline = (
        candidate_metric >= baseline_metric
        if higher_is_better
        else candidate_metric <= baseline_metric
    )
    if not beats_baseline:
        return PromotionDecision(
            record_id=candidate["record_id"],
            model_type=model_type,
            promoted=False,
            reason=(
                f"Did not beat baseline {baseline_type!r} on {metric_name}: "
                f"candidate={candidate_metric!r}, baseline={baseline_metric!r}."
            ),
            candidate_metric=candidate_metric,
            baseline_metric=baseline_metric,
            previous_production_metric=None,
        )

    current_production = registry.get_active(model_type)
    previous_production_metric = (
        _extract_metric(current_production, metric_path) if current_production is not None else None
    )
    if previous_production_metric is not None:
        regresses = (
            candidate_metric < previous_production_metric
            if higher_is_better
            else candidate_metric > previous_production_metric
        )
        if regresses:
            return PromotionDecision(
                record_id=candidate["record_id"],
                model_type=model_type,
                promoted=False,
                reason=(
                    f"Beat baseline but regressed vs current PRODUCTION on {metric_name}: "
                    f"candidate={candidate_metric!r}, active={previous_production_metric!r}."
                ),
                candidate_metric=candidate_metric,
                baseline_metric=baseline_metric,
                previous_production_metric=previous_production_metric,
            )

    reason = (
        f"Beat baseline {baseline_type!r} on {metric_name} "
        f"({baseline_metric!r} -> {candidate_metric!r})"
    )
    reason += (
        f"; improved over current PRODUCTION ({previous_production_metric!r})"
        if previous_production_metric is not None
        else "; no prior PRODUCTION model of this type to compare against"
    )
    return PromotionDecision(
        record_id=candidate["record_id"],
        model_type=model_type,
        promoted=True,
        reason=reason,
        candidate_metric=candidate_metric,
        baseline_metric=baseline_metric,
        previous_production_metric=previous_production_metric,
    )


def apply_promotion(registry: ModelRegistry, candidate: dict) -> PromotionDecision:
    """Evaluates the gate and mutates the registry accordingly: promotes
    the candidate to `PRODUCTION` (archiving whatever was `PRODUCTION`
    before it — at most one `PRODUCTION` record per `model_type` at a
    time), or marks it `FAILED`. Idempotent to call twice on the same
    already-decided candidate (it will just re-evaluate and re-apply the
    same decision)."""
    decision = evaluate_promotion(registry, candidate)
    if decision.promoted:
        current_production = registry.get_active(candidate["model_type"])
        if current_production is not None:
            registry.set_status(
                current_production["record_id"],
                ModelStatus.ARCHIVED,
                reason=f"Superseded by {candidate['record_id']}",
            )
        registry.set_status(candidate["record_id"], ModelStatus.PRODUCTION, reason=decision.reason)
    else:
        registry.set_status(candidate["record_id"], ModelStatus.FAILED, reason=decision.reason)
    return decision
