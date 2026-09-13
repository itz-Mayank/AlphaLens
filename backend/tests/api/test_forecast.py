"""API tests for the Phase 6 forecast/explanation endpoints. Uses the REAL
model registry produced by `ml/scripts/run_real_experiment.py` (real,
already-trained XGBoost artifacts) and real (not mocked) demo-provider
price data — these exercise the actual save/load/predict path end to end,
not a stand-in.

Requires `ml/experiments/registry.json` to exist (run
`ml/scripts/run_real_experiment.py` first) — these tests are skipped, not
failed, if it doesn't, since a missing registry is itself a legitimate,
separately-tested state (`test_forecast_returns_503_when_model_registry_is_missing`).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.db.models.job import JobType
from app.repositories.job_repository import JobRepository
from app.services.market_data_service import run_ingestion

_REGISTRY_EXISTS = Path(get_settings().ml_registry_path).exists()


def _ingest_recent(db_session, tickers, *, lookback_days=150):
    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback_days)
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()


def test_forecast_requires_authentication(client):
    res = client.get("/api/v1/stocks/AAPL/forecast")
    assert res.status_code == 401


def test_forecast_404_for_ticker_unknown_to_this_deployment(client, auth_headers):
    res = client.get("/api/v1/stocks/ZZZZ/forecast", headers=auth_headers)
    assert res.status_code == 404


@pytest.mark.skipif(
    not _REGISTRY_EXISTS, reason="no trained model registry - run the real experiment first"
)
class TestForecastWithRealModels:
    def test_forecast_returns_a_real_prediction_with_full_provenance(
        self, client, auth_headers, db_session
    ):
        _ingest_recent(db_session, ["AAPL"])

        res = client.get("/api/v1/stocks/AAPL/forecast", headers=auth_headers)

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ticker"] == "AAPL"
        assert body["model_name"] == "xgboost"
        assert body["predicted_direction"] in {"Bearish", "Neutral", "Bullish"}
        assert isinstance(body["expected_return"], float)
        assert set(body["probabilities"]) == {"Bearish", "Neutral", "Bullish"}
        assert body["data_source"] == "demo"  # honest disclosure, never hidden
        assert body["horizon_days"] == 5
        assert body["feature_version"]
        assert body["dataset_version"]
        assert body["return_model_version"]
        assert body["direction_model_version"]
        assert body["prediction_timestamp"]
        assert body["data_timestamp"]
        assert "not financial advice" in body["disclaimer"].lower()
        # Model freshness (product-reset requirement): the real registry
        # already records train/test periods — this is the first
        # customer-facing endpoint to surface them, so a user can see how
        # old the model's training snapshot actually is relative to now.
        assert body["training_period_start"]
        assert body["training_period_end"]
        assert body["evaluation_period_end"]
        assert body["training_period_start"] < body["training_period_end"]
        assert body["training_period_end"] <= body["evaluation_period_end"]

    def test_forecast_422_for_insufficient_history(self, client, auth_headers, db_session):
        _ingest_recent(db_session, ["GOOGL"], lookback_days=10)

        res = client.get("/api/v1/stocks/GOOGL/forecast", headers=auth_headers)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "INSUFFICIENT_HISTORY"

    def test_forecast_422_for_a_ticker_outside_the_trained_universe(
        self, client, auth_headers, db_session
    ):
        # TSLA is in the demo provider's universe (so it's a known security
        # to this deployment) but NOT one of the 11 tickers the registered
        # model was trained on.
        _ingest_recent(db_session, ["TSLA"])

        res = client.get("/api/v1/stocks/TSLA/forecast", headers=auth_headers)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "UNSUPPORTED_TICKER"

    def test_forecast_is_never_hardcoded_predictions_differ_across_tickers(
        self, client, auth_headers, db_session
    ):
        _ingest_recent(db_session, ["AAPL", "MSFT"])

        aapl = client.get("/api/v1/stocks/AAPL/forecast", headers=auth_headers).json()
        msft = client.get("/api/v1/stocks/MSFT/forecast", headers=auth_headers).json()

        assert (aapl["expected_return"], aapl["predicted_direction"]) != (
            msft["expected_return"],
            msft["predicted_direction"],
        )

    def test_explanation_requires_authentication(self, client):
        res = client.get("/api/v1/stocks/AAPL/forecast/explanation")
        assert res.status_code == 401

    def test_explanation_returns_meaningful_top_factors(self, client, auth_headers, db_session):
        _ingest_recent(db_session, ["AAPL"])

        res = client.get("/api/v1/stocks/AAPL/forecast/explanation?top_n=3", headers=auth_headers)

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ticker"] == "AAPL"
        assert len(body["top_direction_factors"]) == 3
        assert len(body["top_return_factors"]) == 3
        for factor in body["top_direction_factors"] + body["top_return_factors"]:
            assert set(factor) == {"feature", "value", "contribution", "direction"}
            assert factor["direction"] in {"positive", "negative"}
        assert "does not establish causality" in body["methodology_note"].lower()

    def test_explanation_top_n_is_configurable(self, client, auth_headers, db_session):
        _ingest_recent(db_session, ["AAPL"])

        res = client.get("/api/v1/stocks/AAPL/forecast/explanation?top_n=7", headers=auth_headers)

        assert res.status_code == 200
        body = res.json()
        assert len(body["top_direction_factors"]) == 7
        assert len(body["top_return_factors"]) == 7

    def test_explanation_422_for_unsupported_ticker(self, client, auth_headers, db_session):
        _ingest_recent(db_session, ["TSLA"])

        res = client.get("/api/v1/stocks/TSLA/forecast/explanation", headers=auth_headers)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "UNSUPPORTED_TICKER"


def test_forecast_returns_503_when_model_registry_is_missing(
    client, auth_headers, db_session, monkeypatch, tmp_path
):
    _ingest_recent(db_session, ["AAPL"])
    monkeypatch.setattr(get_settings(), "ml_registry_path", str(tmp_path / "no_registry_here.json"))

    res = client.get("/api/v1/stocks/AAPL/forecast", headers=auth_headers)

    assert res.status_code == 503
    assert res.json()["error"]["code"] == "MODEL_UNAVAILABLE"
