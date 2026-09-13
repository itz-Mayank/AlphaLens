from datetime import date
from decimal import Decimal

from app.db.models.job import Job, JobStatus, JobType
from app.db.models.price_bar import PriceBar
from app.db.models.security import DataSource, Security
from app.repositories.job_repository import JobRepository
from app.services.market_data_service import run_ingestion
from sqlalchemy import func, select


def _create_job(db_session) -> Job:
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    return job


def test_run_ingestion_creates_security_and_price_bars(db_session):
    job = _create_job(db_session)

    run_ingestion(
        db_session,
        job_id=job.id,
        tickers=["AAPL"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 3, 31),
    )

    security = db_session.execute(select(Security).where(Security.ticker == "AAPL")).scalar_one()
    assert security.data_source == DataSource.DEMO
    assert security.name == "Apple Inc."

    bar_count = db_session.execute(
        select(func.count()).select_from(PriceBar).where(PriceBar.security_id == security.id)
    ).scalar_one()
    assert bar_count > 50  # ~64 weekdays in Q1 2023

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.started_at is not None
    assert job.completed_at is not None
    assert job.extra["per_ticker"]["AAPL"]["bars_written"] == bar_count


def test_run_ingestion_is_idempotent(db_session):
    job1 = _create_job(db_session)
    run_ingestion(
        db_session,
        job_id=job1.id,
        tickers=["MSFT"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 6, 30),
    )

    security = db_session.execute(select(Security).where(Security.ticker == "MSFT")).scalar_one()
    count_after_first = db_session.execute(
        select(func.count()).select_from(PriceBar).where(PriceBar.security_id == security.id)
    ).scalar_one()

    # Re-ingesting the exact same window must not create duplicate rows —
    # this is only a meaningful assertion because DemoMarketDataProvider is
    # deterministic (same ticker/end -> same bars every time).
    job2 = _create_job(db_session)
    run_ingestion(
        db_session,
        job_id=job2.id,
        tickers=["MSFT"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 6, 30),
    )

    count_after_second = db_session.execute(
        select(func.count()).select_from(PriceBar).where(PriceBar.security_id == security.id)
    ).scalar_one()

    assert count_after_second == count_after_first

    # A wider window (superset) should extend, not duplicate, existing rows.
    job3 = _create_job(db_session)
    run_ingestion(
        db_session,
        job_id=job3.id,
        tickers=["MSFT"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 12, 31),
    )
    count_after_wider = db_session.execute(
        select(func.count()).select_from(PriceBar).where(PriceBar.security_id == security.id)
    ).scalar_one()
    assert count_after_wider > count_after_second


def test_run_ingestion_defaults_to_the_full_universe_when_no_tickers_given(db_session):
    job = _create_job(db_session)

    run_ingestion(
        db_session,
        job_id=job.id,
        tickers=None,
        start_date=date(2023, 1, 1),
        end_date=date(2023, 1, 31),
    )

    security_count = db_session.execute(select(func.count()).select_from(Security)).scalar_one()
    assert security_count >= 10

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert len(job.extra["tickers"]) == security_count


def test_run_ingestion_records_unknown_tickers_without_failing_the_job(db_session):
    job = _create_job(db_session)

    run_ingestion(
        db_session,
        job_id=job.id,
        tickers=["AAPL", "NOTATICKER"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 1, 31),
    )

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.extra["unknown_tickers"] == ["NOTATICKER"]
    assert "AAPL" in job.extra["per_ticker"]


def test_run_ingestion_falls_back_to_the_curated_universe_for_a_provider_with_no_universe(
    db_session,
):
    """A real provider like Twelve Data deliberately raises
    NotImplementedError from list_securities() (it covers far too many
    instruments to enumerate) — ingestion must still resolve real
    company metadata (name/exchange/sector) from AlphaLens's own curated
    list rather than crashing or recording every requested ticker as
    unknown. Regression test for the bug where `run_ingestion`
    unconditionally called `provider.list_securities()`."""
    from app.providers.base import OHLCVBar

    class _EnumerationFreeProvider:
        data_source = "external"

        def list_securities(self):
            raise NotImplementedError("real vendor — no fixed universe")

        def get_daily_bars(self, ticker, start, end):
            return [
                OHLCVBar(
                    ts=date(2023, 1, 3),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10.5"),
                    adjusted_close=Decimal("10.5"),
                    volume=1000,
                )
            ]

    job = _create_job(db_session)

    run_ingestion(
        db_session,
        job_id=job.id,
        tickers=["AAPL"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 1, 31),
        provider=_EnumerationFreeProvider(),
    )

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.extra["unknown_tickers"] == []

    security = db_session.execute(select(Security).where(Security.ticker == "AAPL")).scalar_one()
    assert security.name == "Apple Inc."
    # The real provider's own data_source ("external"), never hardcoded "demo".
    assert security.data_source == DataSource.EXTERNAL


def test_run_ingestion_discovers_a_genuinely_new_ticker_via_search(db_session):
    """AMD is neither in the provider's own (nonexistent) universe nor in
    AlphaLens's curated fallback list — only a live search lookup (Twelve
    Data's real symbol_search, mocked here) can resolve its metadata. This
    is the exact scenario the product reset calls for: researching a
    ticker nobody pre-registered anywhere."""
    from app.providers.base import OHLCVBar, SecurityInfo

    class _SearchableProvider:
        data_source = "external"

        def list_securities(self):
            raise NotImplementedError

        def search_securities(self, query, *, limit=10):
            if query == "AMD":
                return [
                    SecurityInfo("AMD", "Advanced Micro Devices, Inc.", "NASDAQ", "Technology", "Semiconductors", "USD")
                ]
            return []

        def get_daily_bars(self, ticker, start, end):
            return [
                OHLCVBar(
                    ts=date(2023, 1, 3),
                    open=Decimal("70"),
                    high=Decimal("71"),
                    low=Decimal("69"),
                    close=Decimal("70.5"),
                    adjusted_close=Decimal("70.5"),
                    volume=500,
                )
            ]

    job = _create_job(db_session)

    run_ingestion(
        db_session,
        job_id=job.id,
        tickers=["AMD"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 1, 31),
        provider=_SearchableProvider(),
    )

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.extra["unknown_tickers"] == []

    security = db_session.execute(select(Security).where(Security.ticker == "AMD")).scalar_one()
    assert security.name == "Advanced Micro Devices, Inc."
    assert security.data_source == DataSource.EXTERNAL


def test_run_ingestion_marks_job_failed_on_unexpected_error(db_session):
    from app.providers.base import SecurityInfo

    class _BoomProvider:
        data_source = "demo"

        def list_securities(self):
            return [SecurityInfo("AAPL", "Apple Inc.", "NASDAQ", "Technology", None, "USD")]

        def get_daily_bars(self, ticker, start, end):
            raise RuntimeError("provider exploded")

    job = _create_job(db_session)

    run_ingestion(
        db_session,
        job_id=job.id,
        tickers=["AAPL"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 1, 31),
        provider=_BoomProvider(),
    )

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "provider exploded" in job.error
