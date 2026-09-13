"""Integration tests for `app/services/alert_evaluation_service.py`:
per-type deterministic evaluation, cooldown/deduplication, idempotent
behavior across repeated evaluation cycles (simulating concurrent workers
via the same row-level-locking code path), and missing-data handling.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.db.models.job import JobType
from app.db.models.security import Security
from app.db.models.user import User, UserRole
from app.repositories.alert_repository import AlertRepository
from app.repositories.job_repository import JobRepository
from app.services.alert_evaluation_service import evaluate_all_alerts
from app.services.market_data_service import run_ingestion
from ml.registry.registry import ModelRegistry


def _forecast_model_available() -> bool:
    """Same real-PRODUCTION-model check `forecast_service.get_forecast`
    itself depends on (see ml.inference.serving.load_forecast_models) —
    a fresh checkout with no trained-and-promoted model yet is a real,
    expected state (not a failure), matching `test_forecast.py`'s
    `_REGISTRY_EXISTS` pattern one level more precisely: the registry file
    can exist without anything in it having passed the promotion gate."""
    registry_path = Path(get_settings().ml_registry_path)
    if not registry_path.exists():
        return False
    registry = ModelRegistry(registry_path)
    return registry.get_active("xgboost_direction") is not None


_FORECAST_MODEL_AVAILABLE = _forecast_model_available()


def _make_user(db_session, email="alert-eval-test@example.com") -> User:
    user = User(email=email, password_hash="x", full_name="Alert Eval Test", role=UserRole.USER)
    db_session.add(user)
    db_session.flush()
    return user


def _seed_security(db_session, ticker="AAPL") -> Security:
    security = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(security)
    db_session.flush()
    return security


def _ingest_prices(db_session, tickers, lookback_days=200) -> None:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback_days)
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()


class TestPriceThresholdEvaluation:
    def test_price_above_fires_when_the_condition_is_genuinely_met(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        alert = AlertRepository(db_session).create(
            user_id=user.id,
            security_id=security.id,
            alert_type="PRICE_ABOVE",
            config={"threshold": 0.01},
            cooldown_minutes=60,  # near-zero: any real demo price clears it
        )
        db_session.flush()

        summary = evaluate_all_alerts(db_session)
        assert summary.triggered == 1

        events, total = AlertRepository(db_session).list_events_for_alert(
            alert_id=alert.id, limit=10, offset=0
        )
        assert total == 1
        assert events[0].observed_value["price"] > 0.01

    def test_price_above_does_not_fire_when_condition_is_not_met(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        AlertRepository(db_session).create(
            user_id=user.id, security_id=security.id, alert_type="PRICE_ABOVE",
            config={"threshold": 999_999_999}, cooldown_minutes=60,
        )
        db_session.flush()

        summary = evaluate_all_alerts(db_session)
        assert summary.triggered == 0


class TestCooldownDeduplication:
    def test_a_still_true_condition_does_not_refire_within_the_cooldown_window(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        AlertRepository(db_session).create(
            user_id=user.id, security_id=security.id, alert_type="PRICE_ABOVE",
            config={"threshold": 0.01}, cooldown_minutes=60,
        )
        db_session.flush()

        first = evaluate_all_alerts(db_session)
        assert first.triggered == 1

        second = evaluate_all_alerts(db_session)
        assert second.triggered == 0
        assert second.skipped_cooldown == 1

        alert = AlertRepository(db_session).list_for_user(user_id=user.id)[0]
        events, total = AlertRepository(db_session).list_events_for_alert(
            alert_id=alert.id, limit=10, offset=0
        )
        assert total == 1  # still only one event — no duplicate firing

    def test_a_condition_can_refire_after_the_cooldown_window_elapses(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        alert = AlertRepository(db_session).create(
            user_id=user.id, security_id=security.id, alert_type="PRICE_ABOVE",
            config={"threshold": 0.01}, cooldown_minutes=1,
        )
        db_session.flush()

        now = datetime.now(UTC)
        evaluate_all_alerts(db_session, as_of=now)
        second = evaluate_all_alerts(db_session, as_of=now + timedelta(minutes=2))
        assert second.triggered == 1

        events, total = AlertRepository(db_session).list_events_for_alert(
            alert_id=alert.id, limit=10, offset=0
        )
        assert total == 2

    def test_repeated_evaluation_cycles_never_duplicate_events_simulating_concurrent_workers(
        self, db_session
    ):
        """Runs the same evaluation logic 5 times in a row at the same
        `as_of` — the row-lock + cooldown check must make this idempotent,
        the same guarantee that protects against two concurrent Celery
        workers evaluating the same alert."""
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        alert = AlertRepository(db_session).create(
            user_id=user.id, security_id=security.id, alert_type="PRICE_ABOVE",
            config={"threshold": 0.01}, cooldown_minutes=60,
        )
        db_session.flush()

        now = datetime.now(UTC)
        for _ in range(5):
            evaluate_all_alerts(db_session, as_of=now)

        events, total = AlertRepository(db_session).list_events_for_alert(
            alert_id=alert.id, limit=10, offset=0
        )
        assert total == 1


class TestMissingDataHandling:
    def test_a_security_with_no_price_data_is_skipped_not_errored_or_fired(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session, "NODATA")
        AlertRepository(db_session).create(
            user_id=user.id, security_id=security.id, alert_type="PRICE_ABOVE",
            config={"threshold": 1}, cooldown_minutes=60,
        )
        db_session.flush()

        summary = evaluate_all_alerts(db_session)
        assert summary.triggered == 0
        assert summary.errors == 0
        assert summary.skipped_no_data == 1


@pytest.mark.skipif(
    not _FORECAST_MODEL_AVAILABLE,
    reason="No PRODUCTION forecast model registered yet — run ml/scripts/run_real_experiment.py.",
)
class TestForecastClassChangeBaseline:
    def test_the_first_evaluation_establishes_a_baseline_and_never_fires(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        alert = AlertRepository(db_session).create(
            user_id=user.id, security_id=security.id, alert_type="FORECAST_CLASS_CHANGE",
            config={}, cooldown_minutes=60,
        )
        db_session.flush()

        summary = evaluate_all_alerts(db_session)
        assert summary.triggered == 0
        # Same identity-mapped object within this session — no refresh
        # needed (and refresh() would discard the not-yet-flushed update,
        # since this fixture's session runs with autoflush=False).
        assert alert.last_observed_state is not None
        assert "predicted_class" in alert.last_observed_state

    def test_an_unchanged_forecast_class_on_the_second_pass_does_not_fire(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        AlertRepository(db_session).create(
            user_id=user.id, security_id=security.id, alert_type="FORECAST_CLASS_CHANGE",
            config={}, cooldown_minutes=60,
        )
        db_session.flush()

        first = evaluate_all_alerts(db_session)  # establishes baseline
        assert first.skipped_no_data == 0  # forecast was actually available, not silently skipped
        second = evaluate_all_alerts(db_session)  # forecast is deterministic from the same data
        assert second.skipped_no_data == 0
        assert second.triggered == 0
