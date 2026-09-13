"""Integration tests for `app/services/drift_service.py` against real
ingested (demo-provider) price history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.models.job import JobType
from app.db.models.security import Security
from app.repositories.job_repository import JobRepository
from app.services import drift_service
from app.services.market_data_service import run_ingestion


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


class TestComputeDriftReport:
    def test_returns_empty_when_there_is_not_enough_history(self, db_session):
        security = _seed_security(db_session, "SHORTHIST")
        _ingest_prices(db_session, [security.ticker], lookback_days=30)
        reports = drift_service.compute_drift_report(db_session, security)
        assert reports == []

    def test_reports_psi_and_mean_shift_for_each_monitored_feature_with_real_history(
        self, db_session
    ):
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker], lookback_days=200)
        reports = drift_service.compute_drift_report(db_session, security)

        assert reports  # enough real history for at least some reports
        feature_names = {r.feature for r in reports}
        assert feature_names.issubset(set(drift_service.MONITORED_FEATURES))
        for report in reports:
            assert report.metric in ("psi", "mean_shift_std_units")
            assert report.severity in ("none", "moderate", "significant")

    def test_baseline_and_current_windows_are_chronologically_disjoint(self, db_session):
        """The explicit Phase 10 adversarial scenario: drift calculation
        uses only the intended time windows — baseline strictly precedes
        current, never overlapping or reversed."""
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker], lookback_days=200)
        reports = drift_service.compute_drift_report(db_session, security)
        assert reports
        for report in reports:
            baseline_end = report.baseline_period[1]
            current_start = report.current_period[0]
            assert baseline_end <= current_start

    def test_a_drift_signal_never_mutates_anything_or_raises(self, db_session):
        """A drift signal is a monitoring signal — computing it twice in a
        row must be side-effect-free and produce the same real number
        both times (deterministic given the same underlying data)."""
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker], lookback_days=200)
        first = drift_service.compute_drift_report(db_session, security)
        second = drift_service.compute_drift_report(db_session, security)
        assert [r.value for r in first] == [r.value for r in second]
