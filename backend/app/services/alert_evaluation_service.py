"""Deterministic, per-alert-type alert evaluation — the only place alert
conditions are actually checked. Every alert type here evaluates against
data this deployment actually computes elsewhere (quotes, technical
indicators, forecasts, sentiment aggregates) via the SAME service functions
the REST API and the research agent use — never a reimplementation of that
math, and never a fabricated trigger.

**Cooldown/deduplication**: an alert whose condition is met is only allowed
to fire again after `cooldown_minutes` have passed since its
`last_triggered_at` — this is what stops a still-true condition (e.g.
"price above $200" while the price stays at $210) from creating a new
`AlertEvent` on every single evaluation cycle.

**Idempotency under concurrent evaluation**: each alert row is locked with
`SELECT ... FOR UPDATE` for the duration of its own check-then-fire
sequence, so if two workers ever evaluate the same alert concurrently, the
second one blocks until the first's transaction commits and then re-reads
the now-updated `last_triggered_at` — it cannot also fire for the same
real-world condition (see
`tests/integration/test_alert_evaluation_service.py::TestConcurrentEvaluation`).

**CHANGE-detection alert types** (`FORECAST_CLASS_CHANGE`,
`SENTIMENT_CHANGE`) need a previous value to compare against, which is not
persisted anywhere else (forecasts/sentiment are computed on demand, not
stored historically) — `Alert.last_observed_state` is the evaluator's own
scratch memory for this, distinct from `AlertEvent` (which is only ever a
real, user-facing firing). The first evaluation after an alert is created
only establishes this baseline; it never fires an event on that first
pass, since there is nothing yet to have "changed" from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ml.inference.serving import (
    DataValidationFailedError,
    InsufficientHistoryError,
    build_latest_feature_row,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models.alert import Alert, AlertType
from app.db.models.security import Security
from app.repositories.alert_repository import AlertRepository
from app.repositories.price_bar_repository import PriceBarRepository
from app.repositories.security_repository import SecurityRepository
from app.services import forecast_service, news_query_service
from app.services.market_data_service import Quote, fetch_ohlcv_dataframe, quote_from_latest_row

logger = get_logger(__name__)


@dataclass(frozen=True)
class AlertEvaluationSummary:
    evaluated: int
    triggered: int
    skipped_cooldown: int
    skipped_no_data: int
    errors: int


@dataclass(frozen=True)
class _Outcome:
    should_fire: bool
    observed_value: dict[str, Any]
    message: str
    new_state: dict[str, Any] | None


class _NoDataYet(Exception):
    """Raised internally when an alert's condition genuinely cannot be
    evaluated yet (e.g. no quote, insufficient price history) — distinct
    from an evaluation error, and never counted as either a trigger or a
    failure."""


def _evaluate_price_above(alert: Alert, quote: Quote | None) -> _Outcome:
    if quote is None or quote.last_price is None:
        raise _NoDataYet
    threshold = float(alert.config["threshold"])
    fired = float(quote.last_price) > threshold
    return _Outcome(
        should_fire=fired,
        observed_value={"price": float(quote.last_price), "threshold": threshold},
        message=f"{{ticker}} price {float(quote.last_price):.2f} is above {threshold:.2f}",
        new_state=None,
    )


def _evaluate_price_below(alert: Alert, quote: Quote | None) -> _Outcome:
    if quote is None or quote.last_price is None:
        raise _NoDataYet
    threshold = float(alert.config["threshold"])
    fired = float(quote.last_price) < threshold
    return _Outcome(
        should_fire=fired,
        observed_value={"price": float(quote.last_price), "threshold": threshold},
        message=f"{{ticker}} price {float(quote.last_price):.2f} is below {threshold:.2f}",
        new_state=None,
    )


def _evaluate_percent_change_above(alert: Alert, quote: Quote | None) -> _Outcome:
    if quote is None or quote.change_percent is None:
        raise _NoDataYet
    threshold = float(alert.config["threshold_percent"])
    change = float(quote.change_percent)
    fired = change > threshold
    return _Outcome(
        should_fire=fired,
        observed_value={"change_percent": change, "threshold_percent": threshold},
        message=f"{{ticker}} changed {change:+.2f}% (above {threshold:+.2f}%)",
        new_state=None,
    )


def _evaluate_percent_change_below(alert: Alert, quote: Quote | None) -> _Outcome:
    if quote is None or quote.change_percent is None:
        raise _NoDataYet
    threshold = float(alert.config["threshold_percent"])
    change = float(quote.change_percent)
    fired = change < threshold
    return _Outcome(
        should_fire=fired,
        observed_value={"change_percent": change, "threshold_percent": threshold},
        message=f"{{ticker}} changed {change:+.2f}% (below {threshold:+.2f}%)",
        new_state=None,
    )


def _evaluate_forecast_class_change(db: Session, alert: Alert, security: Security) -> _Outcome:
    try:
        result = forecast_service.get_forecast(db, security.ticker)
    except AppError:
        raise _NoDataYet from None
    current_class = result["predicted_direction"]
    previous_class = (alert.last_observed_state or {}).get("predicted_class")
    watch_class = alert.config.get("watch_class")

    if previous_class is None:
        # First observation — establishes the baseline, never fires.
        return _Outcome(
            should_fire=False,
            observed_value={"predicted_class": current_class},
            message="",
            new_state={"predicted_class": current_class},
        )

    changed = current_class != previous_class
    matches_watch = watch_class is None or current_class == watch_class
    fired = changed and matches_watch
    return _Outcome(
        should_fire=fired,
        observed_value={"previous_class": previous_class, "current_class": current_class},
        message=f"{{ticker}} forecast changed from {previous_class} to {current_class}",
        new_state={"predicted_class": current_class},
    )


def _evaluate_sentiment_change(db: Session, alert: Alert, security: Security) -> _Outcome:
    overview = news_query_service.get_sentiment_overview(db, security=security)
    current_score = overview["last_7d"]["average_sentiment_score"]
    if current_score is None:
        raise _NoDataYet
    previous_score = (alert.last_observed_state or {}).get("sentiment_score")

    if previous_score is None:
        return _Outcome(
            should_fire=False,
            observed_value={"sentiment_score": current_score},
            message="",
            new_state={"sentiment_score": current_score},
        )

    threshold_delta = float(alert.config["threshold_delta"])
    delta = abs(current_score - previous_score)
    fired = delta >= threshold_delta
    return _Outcome(
        should_fire=fired,
        observed_value={
            "previous_score": previous_score,
            "current_score": current_score,
            "delta": delta,
            "threshold_delta": threshold_delta,
        },
        message=f"{{ticker}} sentiment moved {delta:.3f} (>= {threshold_delta:.3f})",
        new_state={"sentiment_score": current_score},
    )


_SUPPORTED_INDICATORS = (
    "sma_20", "ema_12", "rsi_14", "macd_line", "macd_signal", "macd_histogram",
    "volatility_20d", "atr_14", "bollinger_percent_b", "relative_volume_20",
)


def _evaluate_technical_threshold(db: Session, alert: Alert, security: Security) -> _Outcome:
    indicator = alert.config["indicator"]
    if indicator not in _SUPPORTED_INDICATORS:
        raise _NoDataYet
    operator = alert.config["operator"]
    threshold = float(alert.config["threshold"])

    history = fetch_ohlcv_dataframe(db, security)
    try:
        feature_row = build_latest_feature_row(history)
    except (InsufficientHistoryError, DataValidationFailedError):
        raise _NoDataYet from None

    value = float(feature_row[indicator])
    fired = value > threshold if operator == "above" else value < threshold
    return _Outcome(
        should_fire=fired,
        observed_value={
            "indicator": indicator,
            "value": value,
            "operator": operator,
            "threshold": threshold,
        },
        message=f"{{ticker}} {indicator} is {value:.4f} ({operator} {threshold:.4f})",
        new_state=None,
    )


def _evaluate_one(
    db: Session, alert: Alert, security: Security, quote: Quote | None
) -> _Outcome | None:
    try:
        if alert.alert_type == AlertType.PRICE_ABOVE:
            return _evaluate_price_above(alert, quote)
        if alert.alert_type == AlertType.PRICE_BELOW:
            return _evaluate_price_below(alert, quote)
        if alert.alert_type == AlertType.PERCENT_CHANGE_ABOVE:
            return _evaluate_percent_change_above(alert, quote)
        if alert.alert_type == AlertType.PERCENT_CHANGE_BELOW:
            return _evaluate_percent_change_below(alert, quote)
        if alert.alert_type == AlertType.FORECAST_CLASS_CHANGE:
            return _evaluate_forecast_class_change(db, alert, security)
        if alert.alert_type == AlertType.SENTIMENT_CHANGE:
            return _evaluate_sentiment_change(db, alert, security)
        if alert.alert_type == AlertType.TECHNICAL_THRESHOLD:
            return _evaluate_technical_threshold(db, alert, security)
    except _NoDataYet:
        return None
    raise ValueError(  # pragma: no cover - exhaustive by construction
        f"Unhandled alert_type '{alert.alert_type}'"
    )


def evaluate_all_alerts(db: Session, *, as_of: datetime | None = None) -> AlertEvaluationSummary:
    """Runs once per Celery Beat tick (see `app/workers/tasks/alerts.py`).
    Loads every enabled alert across every user in one query — deliberately
    NOT user-scoped, unlike everything else in this feature (see
    `AlertRepository.list_enabled_for_evaluation`'s docstring)."""
    as_of = as_of or datetime.now(UTC)
    alert_repo = AlertRepository(db)
    alerts = alert_repo.list_enabled_for_evaluation()

    evaluated = triggered = skipped_cooldown = skipped_no_data = errors = 0
    if not alerts:
        return AlertEvaluationSummary(0, 0, 0, 0, 0)

    security_ids = sorted({a.security_id for a in alerts})
    quotes_by_id = {
        row.security_id: quote_from_latest_row(row)
        for row in PriceBarRepository(db).get_latest_quotes(security_ids=security_ids)
    }
    securities_by_id = {s.id: s for s in SecurityRepository(db).get_by_ids(security_ids)}

    for alert in alerts:
        evaluated += 1
        security = securities_by_id.get(alert.security_id)
        if security is None:
            errors += 1
            logger.error("alert_evaluation_security_missing", alert_id=str(alert.id))
            continue

        # Row-level lock for the remainder of this alert's check-then-fire
        # sequence — held until this iteration's flush, so a concurrent
        # evaluator working the same alert blocks here rather than racing
        # the cooldown check (see this module's docstring).
        locked_alert = db.execute(
            select(Alert).where(Alert.id == alert.id).with_for_update()
        ).scalar_one()

        try:
            outcome = _evaluate_one(db, locked_alert, security, quotes_by_id.get(alert.security_id))
        except Exception as exc:  # noqa: BLE001 - one alert's failure must not abort the batch
            errors += 1
            logger.error("alert_evaluation_failed", alert_id=str(alert.id), error=str(exc))
            continue

        if outcome is None:
            skipped_no_data += 1
            continue

        if outcome.new_state is not None:
            alert_repo.update_last_observed_state(locked_alert, state=outcome.new_state)

        if not outcome.should_fire:
            continue

        if locked_alert.last_triggered_at is not None:
            cooldown_until = locked_alert.last_triggered_at + timedelta(
                minutes=locked_alert.cooldown_minutes
            )
            if as_of < cooldown_until:
                skipped_cooldown += 1
                continue

        alert_repo.create_event(
            alert_id=locked_alert.id,
            triggered_at=as_of,
            observed_value=outcome.observed_value,
            message=outcome.message.format(ticker=security.ticker),
        )
        alert_repo.mark_triggered(locked_alert, triggered_at=as_of)
        db.flush()
        triggered += 1

    return AlertEvaluationSummary(
        evaluated=evaluated,
        triggered=triggered,
        skipped_cooldown=skipped_cooldown,
        skipped_no_data=skipped_no_data,
        errors=errors,
    )
