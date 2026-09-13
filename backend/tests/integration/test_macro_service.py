from datetime import date
from decimal import Decimal

from app.db.models.job import Job, JobStatus, JobType
from app.providers.base import MacroObservationData
from app.providers.http_client import ProviderUnavailableError
from app.repositories.job_repository import JobRepository
from app.services.macro_service import get_macro_series, run_ingestion


class _FakeProvider:
    def __init__(self, observations=None, error=None):
        self._observations = observations or []
        self._error = error

    def get_observations(self, series_id, *, start, end):
        if self._error:
            raise self._error
        return self._observations


def _create_job(db_session) -> Job:
    job = JobRepository(db_session).create(
        job_type=JobType.MACRO_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    return job


def test_run_ingestion_writes_observations_and_completes_the_job(db_session):
    job = _create_job(db_session)
    obs = [
        MacroObservationData(
            series_id="FEDFUNDS", observation_date=date(2024, 1, 1), value=Decimal("5.33"),
            unit="Percent", frequency="Monthly", vintage_date=date(2024, 2, 1),
        )
    ]

    run_ingestion(
        db_session, job_id=job.id, series_id="FEDFUNDS",
        start=date(2024, 1, 1), end=date(2024, 1, 31), provider=_FakeProvider(observations=obs),
    )

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.extra["observations_written"] == 1

    report = get_macro_series(db_session, series_id="FEDFUNDS")
    assert report.available is True
    assert report.observations[0].value == "5.330000"  # Numeric(20, 6) column precision


def test_run_ingestion_marks_job_failed_on_provider_error(db_session):
    job = _create_job(db_session)
    run_ingestion(
        db_session, job_id=job.id, series_id="FEDFUNDS",
        start=date(2024, 1, 1), end=date(2024, 1, 31),
        provider=_FakeProvider(error=ProviderUnavailableError("FRED is down")),
    )
    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "down" in job.error


def test_get_macro_series_reports_unavailable_when_nothing_ingested(db_session):
    report = get_macro_series(db_session, series_id="UNRATE")
    assert report.available is False
    assert report.observations == []
