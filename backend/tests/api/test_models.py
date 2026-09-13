"""API-level tests for /api/v1/models: RBAC (ANALYST/ADMIN only, matching
market-data ingestion's restriction), registry listing, live performance,
drift, and the retrain trigger."""

from unittest.mock import patch

from app.db.models.security import Security


def _seed_security(db_session, ticker="AAPL") -> Security:
    security = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(security)
    db_session.flush()
    return security


class TestRoleBasedAccess:
    def test_a_plain_user_cannot_list_models(self, client, auth_headers):
        res = client.get("/api/v1/models", headers=auth_headers)
        assert res.status_code == 403

    def test_a_plain_user_cannot_trigger_retraining(self, client, auth_headers):
        res = client.post("/api/v1/models/retrain", headers=auth_headers)
        assert res.status_code == 403

    def test_an_analyst_can_list_models(self, client, make_user_with_role):
        headers = make_user_with_role("ANALYST")
        res = client.get("/api/v1/models", headers=headers)
        assert res.status_code == 200

    def test_unauthenticated_requests_are_rejected(self, client):
        assert client.get("/api/v1/models").status_code == 401


class TestListModels:
    def test_returns_a_list_reflecting_the_real_registry_file(self, client, make_user_with_role):
        headers = make_user_with_role("ADMIN")
        res = client.get("/api/v1/models", headers=headers)
        assert res.status_code == 200
        assert isinstance(res.json(), list)


class TestLivePerformance:
    def test_reports_insufficient_data_for_a_model_type_with_no_matured_predictions(
        self, client, make_user_with_role
    ):
        headers = make_user_with_role("ADMIN")
        res = client.get("/api/v1/models/xgboost_return/performance", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["insufficient_data"] is True
        assert "not this model's training/backtest metrics" in body["disclaimer"]


class TestDriftReport:
    def test_unknown_ticker_is_a_404(self, client, make_user_with_role):
        headers = make_user_with_role("ADMIN")
        res = client.get("/api/v1/models/drift/ZZZZ", headers=headers)
        assert res.status_code == 404

    def test_known_ticker_with_no_price_history_returns_an_empty_report_not_an_error(
        self, client, make_user_with_role, db_session
    ):
        _seed_security(db_session, "AAPL")
        headers = make_user_with_role("ADMIN")
        res = client.get("/api/v1/models/drift/AAPL", headers=headers)
        assert res.status_code == 200
        assert res.json()["reports"] == []


class TestTriggerRetraining:
    def test_enqueues_a_job_and_dispatches_the_celery_task(self, client, make_user_with_role):
        headers = make_user_with_role("ADMIN")
        with patch("app.api.v1.models.retrain_models_task.delay") as mock_delay:
            res = client.post("/api/v1/models/retrain", headers=headers)
        assert res.status_code == 202
        body = res.json()
        assert body["status"] == "QUEUED"
        mock_delay.assert_called_once_with(body["job_id"])

        job_res = client.get(f"/api/v1/jobs/{body['job_id']}", headers=headers)
        assert job_res.status_code == 200
        assert job_res.json()["job_type"] == "MODEL_RETRAINING"
