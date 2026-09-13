"""API-level tests for /api/v1/alerts: typed config validation and
cross-user ownership isolation (CRITICAL per Phase 9)."""

from app.db.models.security import Security


def _seed_security(db_session, ticker="AAPL") -> Security:
    security = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(security)
    db_session.flush()
    return security


def _second_user_headers(client) -> dict:
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "second-alert-user@example.com",
            "password": "correct-horse-9",
            "full_name": "Second User",
        },
    )
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create_alert(client, headers, ticker="AAPL", threshold=200) -> dict:
    res = client.post(
        "/api/v1/alerts",
        json={"ticker": ticker, "config": {"alert_type": "PRICE_ABOVE", "threshold": threshold}},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


class TestCrudAndValidation:
    def test_requires_authentication(self, client):
        assert client.get("/api/v1/alerts").status_code == 401

    def test_create_requires_a_valid_typed_config(self, client, auth_headers, db_session):
        _seed_security(db_session)
        res = client.post(
            "/api/v1/alerts",
            json={"ticker": "AAPL", "config": {"alert_type": "PRICE_ABOVE"}},  # missing threshold
            headers=auth_headers,
        )
        assert res.status_code == 422

    def test_create_rejects_an_unknown_alert_type(self, client, auth_headers, db_session):
        _seed_security(db_session)
        res = client.post(
            "/api/v1/alerts",
            json={"ticker": "AAPL", "config": {"alert_type": "GUARANTEED_PROFIT", "threshold": 1}},
            headers=auth_headers,
        )
        assert res.status_code == 422

    def test_create_unknown_ticker_is_a_404(self, client, auth_headers):
        res = client.post(
            "/api/v1/alerts",
            json={"ticker": "ZZZZ", "config": {"alert_type": "PRICE_ABOVE", "threshold": 200}},
            headers=auth_headers,
        )
        assert res.status_code == 404

    def test_create_list_update_delete(self, client, auth_headers, db_session):
        _seed_security(db_session)
        alert = _create_alert(client, auth_headers)
        assert alert["ticker"] == "AAPL"
        assert alert["enabled"] is True

        listed = client.get("/api/v1/alerts", headers=auth_headers).json()
        assert len(listed) == 1

        updated = client.patch(
            f"/api/v1/alerts/{alert['id']}", json={"enabled": False}, headers=auth_headers
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is False

        res = client.delete(f"/api/v1/alerts/{alert['id']}", headers=auth_headers)
        assert res.status_code == 204
        assert client.get("/api/v1/alerts", headers=auth_headers).json() == []


class TestCrossUserOwnershipIsolation:
    def test_user_b_cannot_read_or_update_user_as_alert(self, client, auth_headers, db_session):
        _seed_security(db_session)
        alert = _create_alert(client, auth_headers)
        b_headers = _second_user_headers(client)

        assert client.patch(
            f"/api/v1/alerts/{alert['id']}", json={"enabled": False}, headers=b_headers
        ).status_code == 404
        assert client.delete(f"/api/v1/alerts/{alert['id']}", headers=b_headers).status_code == 404
        assert (
            client.get(f"/api/v1/alerts/{alert['id']}/events", headers=b_headers).status_code
            == 404
        )

    def test_user_bs_alert_list_never_includes_user_as(self, client, auth_headers, db_session):
        _seed_security(db_session)
        _create_alert(client, auth_headers)
        b_headers = _second_user_headers(client)
        assert client.get("/api/v1/alerts", headers=b_headers).json() == []
