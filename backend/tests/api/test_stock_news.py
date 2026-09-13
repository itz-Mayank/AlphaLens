"""API tests for `/stocks/{ticker}/news`, `/sentiment`, `/sentiment/history`
— real Postgres, real demo news provider, real FinBERT (via
`run_news_ingestion` called directly against `db_session`, same pattern
`test_forecast.py` uses for market data)."""

from datetime import UTC, datetime, timedelta

from app.db.models.job import JobType
from app.db.models.security import Security
from app.repositories.job_repository import JobRepository
from app.services.news_sentiment_service import run_news_ingestion


def _seed_security(db_session, ticker: str = "AAPL", name: str = "Apple Inc.") -> Security:
    security = Security(ticker=ticker, name=name, exchange="NASDAQ", data_source="demo")
    db_session.add(security)
    db_session.flush()
    return security


def _ingest_news(db_session, tickers: list[str], since_days: int = 7) -> None:
    job = JobRepository(db_session).create(
        job_type=JobType.NEWS_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    since = datetime.now(UTC) - timedelta(days=since_days)
    run_news_ingestion(db_session, job_id=job.id, tickers=tickers, since=since)
    db_session.flush()


def test_get_stock_news_requires_authentication(client):
    res = client.get("/api/v1/stocks/AAPL/news")
    assert res.status_code == 401


def test_get_stock_news_404_for_unknown_ticker(client, auth_headers):
    res = client.get("/api/v1/stocks/ZZZZ/news", headers=auth_headers)
    assert res.status_code == 404


def test_get_stock_news_empty_before_ingestion(client, auth_headers, db_session):
    _seed_security(db_session)

    res = client.get("/api/v1/stocks/AAPL/news", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["articles"] == []
    assert body["data_sources"] == []


def test_get_stock_news_returns_real_articles_with_sentiment(client, auth_headers, db_session):
    _seed_security(db_session)
    _ingest_news(db_session, ["AAPL"])

    res = client.get("/api/v1/stocks/AAPL/news?limit=5", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert 0 < len(body["articles"]) <= 5
    assert body["data_sources"] == ["demo"]
    first = body["articles"][0]
    assert first["sentiment"] is not None
    assert first["sentiment"]["predicted_label"] in {"positive", "neutral", "negative"}
    assert first["url"].startswith("https://")


def test_get_stock_sentiment_requires_authentication(client):
    res = client.get("/api/v1/stocks/AAPL/sentiment")
    assert res.status_code == 401


def test_get_stock_sentiment_empty_before_ingestion(client, auth_headers, db_session):
    _seed_security(db_session)

    res = client.get("/api/v1/stocks/AAPL/sentiment", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["last_7d"]["article_count"] == 0
    assert body["last_7d"]["average_sentiment_score"] is None
    assert "not a guaranteed trading signal" in body["disclaimer"].lower()


def test_get_stock_sentiment_reflects_real_ingested_data(client, auth_headers, db_session):
    _seed_security(db_session)
    _ingest_news(db_session, ["AAPL"])

    res = client.get("/api/v1/stocks/AAPL/sentiment", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["last_7d"]["article_count"] > 0
    counted = (
        body["last_7d"]["positive_count"]
        + body["last_7d"]["neutral_count"]
        + body["last_7d"]["negative_count"]
    )
    assert counted == body["last_7d"]["article_count"]


def test_get_stock_sentiment_history_requires_authentication(client):
    res = client.get("/api/v1/stocks/AAPL/sentiment/history")
    assert res.status_code == 401


def test_get_stock_sentiment_history_404_for_unknown_ticker(client, auth_headers):
    res = client.get("/api/v1/stocks/ZZZZ/sentiment/history", headers=auth_headers)
    assert res.status_code == 404


def test_get_stock_sentiment_history_returns_requested_number_of_days(
    client, auth_headers, db_session
):
    _seed_security(db_session)

    res = client.get("/api/v1/stocks/AAPL/sentiment/history?days=10", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert len(body["points"]) == 10
    dates = [p["date"] for p in body["points"]]
    assert dates == sorted(dates)  # oldest first, chart-ready


def test_get_stock_sentiment_history_reflects_real_data(client, auth_headers, db_session):
    _seed_security(db_session)
    _ingest_news(db_session, ["AAPL"])

    res = client.get("/api/v1/stocks/AAPL/sentiment/history?days=10", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    total_articles = sum(p["article_count"] for p in body["points"])
    assert total_articles > 0
