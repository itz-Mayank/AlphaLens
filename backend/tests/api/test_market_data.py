import uuid

from app.db.models.job import Job, JobStatus, JobType


def test_trigger_ingestion_requires_analyst_or_admin_role(client, make_user_with_role, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.market_data.ingest_market_data_task.delay", lambda *a, **k: None
    )
    user_headers = make_user_with_role("USER")

    res = client.post("/api/v1/market-data/ingest", json={}, headers=user_headers)

    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


def test_trigger_ingestion_creates_a_queued_job_for_analyst(
    client, make_user_with_role, db_session, monkeypatch
):
    captured_calls = []
    monkeypatch.setattr(
        "app.api.v1.market_data.ingest_market_data_task.delay",
        lambda *args: captured_calls.append(args),
    )
    analyst_headers = make_user_with_role("ANALYST")

    res = client.post(
        "/api/v1/market-data/ingest",
        json={"tickers": ["aapl", "msft"]},
        headers=analyst_headers,
    )

    assert res.status_code == 202
    body = res.json()
    assert body["status"] == JobStatus.QUEUED

    job = db_session.get(Job, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.job_type == JobType.MARKET_DATA_INGESTION
    assert job.extra["requested_tickers"] == ["AAPL", "MSFT"]  # normalized to uppercase

    # The task was actually dispatched (not skipped), with normalized args.
    assert len(captured_calls) == 1
    dispatched_job_id, dispatched_tickers, _start, _end = captured_calls[0]
    assert dispatched_job_id == str(job.id)
    assert dispatched_tickers == ["AAPL", "MSFT"]


def test_trigger_ingestion_allows_admin_role(client, make_user_with_role, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.market_data.ingest_market_data_task.delay", lambda *a, **k: None
    )
    admin_headers = make_user_with_role("ADMIN")

    res = client.post("/api/v1/market-data/ingest", json={}, headers=admin_headers)

    assert res.status_code == 202


def test_trigger_ingestion_requires_authentication(client):
    res = client.post("/api/v1/market-data/ingest", json={})
    assert res.status_code == 401


def test_get_job_returns_job_status(client, auth_headers, db_session):
    job = Job(job_type=JobType.MARKET_DATA_INGESTION)
    db_session.add(job)
    db_session.flush()

    res = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["status"] == JobStatus.QUEUED


def test_get_job_404_for_unknown_id(client, auth_headers):
    res = client.get(f"/api/v1/jobs/{uuid.uuid4()}", headers=auth_headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_get_job_requires_authentication(client):
    res = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert res.status_code == 401
