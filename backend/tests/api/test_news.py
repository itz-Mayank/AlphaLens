import uuid

from app.db.models.job import Job, JobStatus, JobType


def test_trigger_news_ingestion_requires_analyst_or_admin_role(
    client, make_user_with_role, monkeypatch
):
    monkeypatch.setattr("app.api.v1.news.ingest_news_task.delay", lambda *a, **k: None)
    user_headers = make_user_with_role("USER")

    res = client.post("/api/v1/news/ingest", json={}, headers=user_headers)

    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


def test_trigger_news_ingestion_creates_a_queued_job_for_analyst(
    client, make_user_with_role, db_session, monkeypatch
):
    captured_calls = []
    monkeypatch.setattr(
        "app.api.v1.news.ingest_news_task.delay",
        lambda *args: captured_calls.append(args),
    )
    analyst_headers = make_user_with_role("ANALYST")

    res = client.post(
        "/api/v1/news/ingest", json={"tickers": ["aapl", "msft"]}, headers=analyst_headers
    )

    assert res.status_code == 202
    body = res.json()
    assert body["status"] == JobStatus.QUEUED

    job = db_session.get(Job, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.job_type == JobType.NEWS_INGESTION
    assert job.extra["requested_tickers"] == ["AAPL", "MSFT"]

    assert len(captured_calls) == 1
    dispatched_job_id, dispatched_tickers, _since = captured_calls[0]
    assert dispatched_job_id == str(job.id)
    assert dispatched_tickers == ["AAPL", "MSFT"]


def test_trigger_news_ingestion_allows_admin_role(client, make_user_with_role, monkeypatch):
    monkeypatch.setattr("app.api.v1.news.ingest_news_task.delay", lambda *a, **k: None)
    admin_headers = make_user_with_role("ADMIN")

    res = client.post("/api/v1/news/ingest", json={}, headers=admin_headers)

    assert res.status_code == 202


def test_trigger_news_ingestion_requires_authentication(client):
    res = client.post("/api/v1/news/ingest", json={})
    assert res.status_code == 401
