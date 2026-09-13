"""Prediction logging + live performance monitoring — Phase 10's
PREDICTION -> FUTURE OBSERVATION -> REALIZED OUTCOME -> ERROR/PERFORMANCE
pipeline.

`log_prediction` is called once per real forecast served
(`forecast_service.get_forecast`) — never for a screener row's in-memory
forecast reuse, which would create one row per screener request and
massively over-count how many times a given day's prediction was actually
"made." `evaluate_matured_predictions` is the only place a prediction's
`realized_*` fields are ever filled in, and only once real `PriceBar` rows
prove the horizon has elapsed — never a calendar-day approximation, and
never before the data exists.

`get_live_performance` computes LIVE, OBSERVED performance from matured
predictions only. This is never mixed with TRAINING/BACKTEST performance
(the metrics `ml.registry` stores, or `backtest_service`'s output) — they
measure different things (a model's held-out-test-set performance at
training time vs. this deployment's own actual serving track record) and
conflating them would misrepresent both. See `LivePerformanceReport`'s
`insufficient_data` branch: a model with zero matured predictions yet
reports that honestly rather than a fabricated 0/0 metric.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.prediction_repository import PredictionRepository
from app.repositories.price_bar_repository import PriceBarRepository

ZERO = Decimal(0)

# Bullish/Bearish predictions imply a direction; Neutral is not a
# directional bet and is excluded from hit-rate scoring (matching, never
# fabricating, either "hit" or "miss" for a prediction that made no
# directional claim in the first place).
_DIRECTIONAL_CLASS_EXPECTATION = {"Bullish": "UP", "Bearish": "DOWN"}


def log_prediction(
    db: Session,
    *,
    security_id: int,
    model_type: str,
    model_version: str,
    feature_version: str,
    as_of_date: date,
    horizon_days: int,
    predicted_return: Decimal | None,
    predicted_class: str | None,
    predicted_probabilities: dict | None,
    prediction_timestamp: datetime,
) -> None:
    PredictionRepository(db).create(
        security_id=security_id,
        model_type=model_type,
        model_version=model_version,
        feature_version=feature_version,
        as_of_date=as_of_date,
        horizon_days=horizon_days,
        predicted_return=predicted_return,
        predicted_class=predicted_class,
        predicted_probabilities=predicted_probabilities,
        prediction_timestamp=prediction_timestamp,
    )


def _realized_direction(realized_return: Decimal) -> str:
    if realized_return > ZERO:
        return "UP"
    if realized_return < ZERO:
        return "DOWN"
    return "FLAT"


@dataclass(frozen=True)
class EvaluationSummary:
    evaluated: int
    still_unmatured: int
    errors: int


def evaluate_matured_predictions(
    db: Session, *, as_of: datetime | None = None
) -> EvaluationSummary:
    """Every unevaluated prediction whose horizon has elapsed, scored
    against real subsequent `PriceBar` rows — trading days, counted by
    actual bar rows after `as_of_date`, not a calendar-day approximation
    (which would be wrong across weekends/holidays)."""
    as_of = as_of or datetime.now(UTC)
    prediction_repo = PredictionRepository(db)
    price_bar_repo = PriceBarRepository(db)

    evaluated = still_unmatured = errors = 0
    for prediction in prediction_repo.list_unevaluated():
        as_of_start = datetime.combine(prediction.as_of_date, datetime.min.time(), tzinfo=UTC)
        bars = price_bar_repo.get_range(
            security_id=prediction.security_id, start=as_of_start, end=None
        )
        as_of_index = next(
            (i for i, bar in enumerate(bars) if bar.ts.date() == prediction.as_of_date), None
        )
        if as_of_index is None or as_of_index + prediction.horizon_days >= len(bars):
            still_unmatured += 1
            continue

        as_of_close = bars[as_of_index].close
        future_close = bars[as_of_index + prediction.horizon_days].close
        if as_of_close == ZERO:
            errors += 1
            continue

        realized_return = (future_close - as_of_close) / as_of_close
        prediction_repo.mark_evaluated(
            prediction,
            realized_return=realized_return,
            realized_direction=_realized_direction(realized_return),
            evaluated_at=as_of,
        )
        # Flushed immediately (not just once after the loop) so a caller
        # re-querying within the same session/transaction — including
        # `list_unevaluated` if this function were ever called twice in a
        # row without an intervening commit — always sees this row as
        # evaluated, never re-selects it as still-pending.
        db.flush()
        evaluated += 1

    return EvaluationSummary(evaluated=evaluated, still_unmatured=still_unmatured, errors=errors)


@dataclass(frozen=True)
class LivePerformanceReport:
    model_type: str
    insufficient_data: bool
    reason: str | None
    sample_count: int
    mae: float | None
    rmse: float | None
    directional_hit_rate: float | None
    directional_sample_count: int
    disclaimer: str = (
        "Live, observed performance from this deployment's own matured predictions — "
        "not this model's training/backtest metrics (see the model registry for those). "
        "The two measure different things and are never combined."
    )


def get_live_performance(db: Session, *, model_type: str) -> LivePerformanceReport:
    predictions = PredictionRepository(db).list_evaluated(model_type=model_type)
    if not predictions:
        return LivePerformanceReport(
            model_type=model_type,
            insufficient_data=True,
            reason="No matured predictions yet for this model type.",
            sample_count=0,
            mae=None,
            rmse=None,
            directional_hit_rate=None,
            directional_sample_count=0,
        )

    return_errors = [
        float(abs(p.predicted_return - p.realized_return))
        for p in predictions
        if p.predicted_return is not None and p.realized_return is not None
    ]
    squared_errors = [
        float((p.predicted_return - p.realized_return) ** 2)
        for p in predictions
        if p.predicted_return is not None and p.realized_return is not None
    ]
    mae = sum(return_errors) / len(return_errors) if return_errors else None
    rmse = (sum(squared_errors) / len(squared_errors)) ** 0.5 if squared_errors else None

    directional_predictions = [
        p
        for p in predictions
        if p.predicted_class in _DIRECTIONAL_CLASS_EXPECTATION and p.realized_direction is not None
    ]
    hits = 0
    for p in directional_predictions:
        # The membership check above guarantees `predicted_class` is a key
        # of `_DIRECTIONAL_CLASS_EXPECTATION` (so not None) — this just
        # restates that for mypy, which can't narrow across the separate
        # list-comprehension filter above.
        assert p.predicted_class is not None
        if _DIRECTIONAL_CLASS_EXPECTATION[p.predicted_class] == p.realized_direction:
            hits += 1
    directional_hit_rate = (
        hits / len(directional_predictions) if directional_predictions else None
    )

    return LivePerformanceReport(
        model_type=model_type,
        insufficient_data=False,
        reason=None,
        sample_count=len(predictions),
        mae=mae,
        rmse=rmse,
        directional_hit_rate=directional_hit_rate,
        directional_sample_count=len(directional_predictions),
    )
