"""API tests for `POST /api/v1/research/backtest`. Uses the real model
registry and real (not mocked) demo-provider price data, same as
`test_forecast.py` — skipped if no trained registry exists."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.db.models.job import JobType
from app.repositories.job_repository import JobRepository
from app.services.market_data_service import run_ingestion

_REGISTRY_EXISTS = Path(get_settings().ml_registry_path).exists()


def _ingest_recent(db_session, tickers, *, lookback_days=200):
    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback_days)
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()
    return start, end


def test_backtest_requires_authentication(client):
    res = client.post(
        "/api/v1/research/backtest",
        json={"tickers": ["AAPL"], "start_date": "2024-01-01", "end_date": "2024-06-01"},
    )
    assert res.status_code == 401


def test_backtest_404_for_unknown_ticker(client, auth_headers):
    res = client.post(
        "/api/v1/research/backtest",
        json={"tickers": ["ZZZZ"], "start_date": "2024-01-01", "end_date": "2024-06-01"},
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_backtest_rejects_end_before_start(client, auth_headers):
    res = client.post(
        "/api/v1/research/backtest",
        json={"tickers": ["AAPL"], "start_date": "2024-06-01", "end_date": "2024-01-01"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_backtest_rejects_too_many_tickers(client, auth_headers):
    res = client.post(
        "/api/v1/research/backtest",
        json={
            "tickers": [f"T{i}" for i in range(21)],
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
        },
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.skipif(
    not _REGISTRY_EXISTS, reason="no trained model registry - run the real experiment first"
)
class TestBacktestWithRealModels:
    def test_backtest_returns_a_real_equity_curve_and_metrics(
        self, client, auth_headers, db_session
    ):
        start, end = _ingest_recent(db_session, ["AAPL", "MSFT", "JPM"])

        res = client.post(
            "/api/v1/research/backtest",
            json={
                "tickers": ["AAPL", "MSFT", "JPM"],
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "commission_bps": 10,
                "slippage_bps": 5,
            },
            headers=auth_headers,
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert set(body["tickers"]) == {"AAPL", "MSFT", "JPM"}
        assert body["model_name"] == "xgboost_direction"
        assert len(body["equity_curve"]) > 0
        assert all(point["equity"] > 0 for point in body["equity_curve"])
        assert body["data_sources"] == ["demo"]
        metrics = body["metrics"]
        assert isinstance(metrics["cumulative_return"], float)
        assert metrics["max_drawdown"] <= 0
        assert "not a live trading result" in body["disclaimer"].lower()

    def test_higher_transaction_costs_reduce_or_equal_cumulative_return(
        self, client, auth_headers, db_session
    ):
        start, end = _ingest_recent(db_session, ["AAPL", "MSFT"])
        payload = {
            "tickers": ["AAPL", "MSFT"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }

        low = client.post(
            "/api/v1/research/backtest",
            json={**payload, "commission_bps": 0, "slippage_bps": 0},
            headers=auth_headers,
        ).json()
        high = client.post(
            "/api/v1/research/backtest",
            json={**payload, "commission_bps": 200, "slippage_bps": 200},
            headers=auth_headers,
        ).json()

        assert high["metrics"]["cumulative_return"] <= low["metrics"]["cumulative_return"]

    def test_backtest_422_when_no_overlap_with_available_history(
        self, client, auth_headers, db_session
    ):
        _ingest_recent(db_session, ["AAPL"])

        res = client.post(
            "/api/v1/research/backtest",
            json={"tickers": ["AAPL"], "start_date": "1999-01-01", "end_date": "1999-06-01"},
            headers=auth_headers,
        )

        assert res.status_code == 422
