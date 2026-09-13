from datetime import UTC, date, datetime
from decimal import Decimal

from app.db.models.job import Job, JobStatus, JobType
from app.db.models.security import Security
from app.providers.base import CompanyFactsResult, FundamentalFact
from app.providers.http_client import ProviderUnavailableError
from app.repositories.job_repository import JobRepository
from app.services.fundamentals_service import get_fundamentals, run_ingestion


class _FakeProvider:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def get_company_facts(self, ticker):
        if self._error:
            raise self._error
        return self._result


def _security(db_session, ticker: str = "AAPL") -> Security:
    s = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(s)
    db_session.flush()
    return s


def _create_job(db_session) -> Job:
    job = JobRepository(db_session).create(
        job_type=JobType.FUNDAMENTALS_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    return job


def test_run_ingestion_writes_facts_and_completes_the_job(db_session):
    _security(db_session)
    job = _create_job(db_session)
    result = CompanyFactsResult(
        ticker="AAPL", company_name="Apple Inc.", external_id="CIK0000320193",
        facts=[
            FundamentalFact(
                concept="Assets", value=Decimal(100), unit="USD", period_start=None,
                period_end=date(2023, 9, 30), fiscal_year=2023, fiscal_period="FY",
                form="10-K", filed_date=date(2023, 11, 3), accession_number="acc-1",
            )
        ],
        retrieved_at=datetime.now(UTC),
    )

    run_ingestion(db_session, job_id=job.id, ticker="AAPL", provider=_FakeProvider(result=result))

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.extra["facts_written"] == 1
    assert job.extra["available"] is True

    report = get_fundamentals(db_session, ticker="AAPL")
    assert report.available is True
    assert report.facts[0].concept == "Assets"
    assert report.facts[0].value == "100.0000"  # Numeric(24, 4) column precision


def test_run_ingestion_records_provider_returning_none_as_unavailable_not_a_failure(db_session):
    _security(db_session)
    job = _create_job(db_session)

    run_ingestion(db_session, job_id=job.id, ticker="AAPL", provider=_FakeProvider(result=None))

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.extra["available"] is False


def test_run_ingestion_marks_job_failed_on_provider_error(db_session):
    _security(db_session)
    job = _create_job(db_session)

    run_ingestion(
        db_session, job_id=job.id, ticker="AAPL",
        provider=_FakeProvider(error=ProviderUnavailableError("SEC EDGAR is down")),
    )

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "down" in job.error


def test_run_ingestion_fails_the_job_for_an_untracked_ticker(db_session):
    job = _create_job(db_session)
    run_ingestion(db_session, job_id=job.id, ticker="NOPE", provider=_FakeProvider(result=None))
    db_session.refresh(job)
    assert job.status == JobStatus.FAILED


def test_get_fundamentals_returns_none_for_an_untracked_ticker(db_session):
    assert get_fundamentals(db_session, ticker="NOPE") is None


def test_get_fundamentals_reports_unavailable_before_any_ingestion(db_session):
    _security(db_session)
    report = get_fundamentals(db_session, ticker="AAPL")
    assert report.available is False
    assert report.reason is not None
    assert report.facts == []
