"""Proves the Celery task wrapper actually works end to end: a real worker
process would open its OWN DB connection (SessionLocal()), separate from
whatever created the job — so this test deliberately does NOT use the
shared, rolled-back `db_session` fixture (a second physical connection
can't see uncommitted work on another one). It commits for real against
`db_engine` and cleans up afterward.
"""

import pytest
from app.db.models.job import Job, JobStatus, JobType
from app.db.models.security import Security
from app.workers.tasks.market_data import ingest_market_data_task
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def real_session_factory(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)


def test_ingest_market_data_task_runs_end_to_end_in_a_separate_connection(real_session_factory):
    setup = real_session_factory()
    job = Job(job_type=JobType.MARKET_DATA_INGESTION)
    setup.add(job)
    setup.commit()
    job_id = job.id
    setup.close()

    try:
        ingest_market_data_task.run(str(job_id), ["AAPL"], "2023-01-01", "2023-01-31")

        verify = real_session_factory()
        refreshed = verify.get(Job, job_id)
        assert refreshed.status == JobStatus.COMPLETED
        assert refreshed.extra["per_ticker"]["AAPL"]["bars_written"] > 0
        verify.close()
    finally:
        cleanup = real_session_factory()
        job_row = cleanup.get(Job, job_id)
        if job_row is not None:
            cleanup.delete(job_row)
        security_row = cleanup.query(Security).filter(Security.ticker == "AAPL").one_or_none()
        if security_row is not None:
            cleanup.delete(security_row)  # cascades to price_bars
        cleanup.commit()
        cleanup.close()


def test_ingest_market_data_task_rolls_back_and_reraises_on_unexpected_error(
    real_session_factory, monkeypatch
):
    setup = real_session_factory()
    job = Job(job_type=JobType.MARKET_DATA_INGESTION)
    setup.add(job)
    setup.commit()
    job_id = job.id
    setup.close()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.workers.tasks.market_data.run_ingestion", _boom)

    try:
        with pytest.raises(RuntimeError, match="boom"):
            ingest_market_data_task.run(str(job_id), ["AAPL"], None, None)
    finally:
        cleanup = real_session_factory()
        job_row = cleanup.get(Job, job_id)
        if job_row is not None:
            cleanup.delete(job_row)
        cleanup.commit()
        cleanup.close()
