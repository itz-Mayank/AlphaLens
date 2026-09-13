"""API-level tests for /api/v1/portfolios: CRUD, transaction creation,
validation errors, and — critically — cross-user ownership isolation
(Phase 9's CRITICAL security requirement: user A must never be able to
access user B's portfolio or transactions, and must see 404, never 403).
"""

from datetime import date

from app.db.models.job import JobType
from app.repositories.job_repository import JobRepository
from app.services.market_data_service import run_ingestion


def _ingest(db_session, tickers, start=date(2023, 1, 1), end=date(2023, 6, 30)):
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()


def _second_user_headers(client) -> dict:
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "second-portfolio-user@example.com",
            "password": "correct-horse-9",
            "full_name": "Second User",
        },
    )
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create_portfolio(client, headers, name="My Portfolio") -> dict:
    res = client.post("/api/v1/portfolios", json={"name": name}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


class TestCrud:
    def test_requires_authentication(self, client):
        assert client.get("/api/v1/portfolios").status_code == 401

    def test_create_and_list_portfolio(self, client, auth_headers):
        _create_portfolio(client, auth_headers)
        res = client.get("/api/v1/portfolios", headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()) == 1

    def test_delete_portfolio(self, client, auth_headers):
        portfolio = _create_portfolio(client, auth_headers)
        res = client.delete(f"/api/v1/portfolios/{portfolio['id']}", headers=auth_headers)
        assert res.status_code == 204
        assert client.get("/api/v1/portfolios", headers=auth_headers).json() == []


class TestTransactionValidation:
    def test_buy_without_ticker_is_a_422(self, client, auth_headers):
        portfolio = _create_portfolio(client, auth_headers)
        res = client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "BUY", "quantity": "10", "price": "100"},
            headers=auth_headers,
        )
        assert res.status_code == 422

    def test_cash_deposit_with_ticker_is_a_422(self, client, auth_headers):
        portfolio = _create_portfolio(client, auth_headers)
        res = client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "CASH_DEPOSIT", "ticker": "AAPL", "amount": "100"},
            headers=auth_headers,
        )
        assert res.status_code == 422

    def test_unknown_ticker_is_a_404(self, client, auth_headers):
        portfolio = _create_portfolio(client, auth_headers)
        client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "CASH_DEPOSIT", "amount": "10000"},
            headers=auth_headers,
        )
        res = client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "BUY", "ticker": "ZZZZ", "quantity": "1", "price": "1"},
            headers=auth_headers,
        )
        assert res.status_code == 404

    def test_a_buy_exceeding_cash_is_a_422_with_a_structured_error(
        self, client, auth_headers, db_session
    ):
        _ingest(db_session, ["AAPL"])
        portfolio = _create_portfolio(client, auth_headers)
        client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "CASH_DEPOSIT", "amount": "100"},
            headers=auth_headers,
        )
        res = client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "BUY", "ticker": "AAPL", "quantity": "10", "price": "100"},
            headers=auth_headers,
        )
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "INSUFFICIENT_CASH"

    def test_a_valid_buy_then_holdings_and_analytics_reflect_it(
        self, client, auth_headers, db_session
    ):
        _ingest(db_session, ["AAPL"])
        portfolio = _create_portfolio(client, auth_headers)
        client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "CASH_DEPOSIT", "amount": "100000"},
            headers=auth_headers,
        )
        res = client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "BUY", "ticker": "AAPL", "quantity": "10", "price": "100"},
            headers=auth_headers,
        )
        assert res.status_code == 201, res.text

        holdings = client.get(
            f"/api/v1/portfolios/{portfolio['id']}/holdings", headers=auth_headers
        )
        assert holdings.status_code == 200
        assert len(holdings.json()) == 1
        assert holdings.json()[0]["ticker"] == "AAPL"

        analytics = client.get(
            f"/api/v1/portfolios/{portfolio['id']}/analytics", headers=auth_headers
        )
        assert analytics.status_code == 200
        assert float(analytics.json()["cash"]) == 99000.0


class TestCrossUserOwnershipIsolation:
    """CRITICAL per Phase 9: user B must get 404, never 403 or real data,
    for any of user A's portfolio-scoped resources."""

    def test_user_b_cannot_read_user_as_portfolio(self, client, auth_headers):
        portfolio = _create_portfolio(client, auth_headers, name="Alice's Portfolio")
        b_headers = _second_user_headers(client)

        res = client.get(f"/api/v1/portfolios/{portfolio['id']}", headers=b_headers)
        assert res.status_code == 404

    def test_user_b_cannot_list_user_as_transactions(self, client, auth_headers, db_session):
        _ingest(db_session, ["AAPL"])
        portfolio = _create_portfolio(client, auth_headers)
        client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "CASH_DEPOSIT", "amount": "1000"},
            headers=auth_headers,
        )
        b_headers = _second_user_headers(client)

        res = client.get(f"/api/v1/portfolios/{portfolio['id']}/transactions", headers=b_headers)
        assert res.status_code == 404

    def test_user_b_cannot_create_a_transaction_on_user_as_portfolio(self, client, auth_headers):
        portfolio = _create_portfolio(client, auth_headers)
        b_headers = _second_user_headers(client)

        res = client.post(
            f"/api/v1/portfolios/{portfolio['id']}/transactions",
            json={"transaction_type": "CASH_DEPOSIT", "amount": "1000"},
            headers=b_headers,
        )
        assert res.status_code == 404

    def test_user_b_cannot_delete_user_as_portfolio(self, client, auth_headers):
        portfolio = _create_portfolio(client, auth_headers)
        b_headers = _second_user_headers(client)

        res = client.delete(f"/api/v1/portfolios/{portfolio['id']}", headers=b_headers)
        assert res.status_code == 404
        # And it's still there for the real owner.
        assert (
            client.get(f"/api/v1/portfolios/{portfolio['id']}", headers=auth_headers).status_code
            == 200
        )

    def test_user_bs_own_portfolio_list_never_includes_user_as_portfolio(
        self, client, auth_headers
    ):
        _create_portfolio(client, auth_headers, name="Alice's Portfolio")
        b_headers = _second_user_headers(client)
        _create_portfolio(client, b_headers, name="Bob's Portfolio")

        res = client.get("/api/v1/portfolios", headers=b_headers)
        names = [p["name"] for p in res.json()]
        assert names == ["Bob's Portfolio"]
