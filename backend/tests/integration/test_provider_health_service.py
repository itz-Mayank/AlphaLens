from app.db.models.job import JobType
from app.repositories.job_repository import JobRepository
from app.services.provider_health_service import get_provider_statuses


def test_reports_all_four_categories_with_no_jobs_run_yet(db_session):
    statuses = {s.category: s for s in get_provider_statuses(db_session)}
    assert set(statuses.keys()) == {"market_data", "news", "fundamentals", "macro"}
    for status in statuses.values():
        assert status.last_success_at is None
        assert status.last_failure_at is None


def test_reflects_a_completed_ingestion_job(db_session):
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    JobRepository(db_session).mark_running(job)
    JobRepository(db_session).mark_completed(job)
    db_session.flush()

    statuses = {s.category: s for s in get_provider_statuses(db_session)}
    assert statuses["market_data"].last_success_at is not None


def test_reflects_a_failed_ingestion_job_with_its_reason(db_session):
    job = JobRepository(db_session).create(
        job_type=JobType.FUNDAMENTALS_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    JobRepository(db_session).mark_running(job)
    JobRepository(db_session).mark_failed(job, error="SEC EDGAR is unreachable")
    db_session.flush()

    statuses = {s.category: s for s in get_provider_statuses(db_session)}
    assert statuses["fundamentals"].last_failure_reason == "SEC EDGAR is unreachable"


def test_demo_env_reports_no_credential_required_for_demo_providers(db_session):
    statuses = {s.category: s for s in get_provider_statuses(db_session)}
    assert statuses["market_data"].configured_provider == "demo"
    assert statuses["market_data"].credential_required is False
    assert statuses["market_data"].credential_configured is True
