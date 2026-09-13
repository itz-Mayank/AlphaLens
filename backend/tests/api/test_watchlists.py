"""API-level tests for /api/v1/watchlists: CRUD, item add/remove, and
cross-user ownership isolation (CRITICAL per Phase 9)."""

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
            "email": "second-watchlist-user@example.com",
            "password": "correct-horse-9",
            "full_name": "Second User",
        },
    )
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create_watchlist(client, headers, name="My Watchlist") -> dict:
    res = client.post("/api/v1/watchlists", json={"name": name}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


class TestCrud:
    def test_requires_authentication(self, client):
        assert client.get("/api/v1/watchlists").status_code == 401

    def test_create_list_and_delete(self, client, auth_headers):
        watchlist = _create_watchlist(client, auth_headers)
        assert client.get("/api/v1/watchlists", headers=auth_headers).json()[0]["item_count"] == 0
        res = client.delete(f"/api/v1/watchlists/{watchlist['id']}", headers=auth_headers)
        assert res.status_code == 204
        assert client.get("/api/v1/watchlists", headers=auth_headers).json() == []

    def test_add_and_remove_item(self, client, auth_headers, db_session):
        _ingest(db_session, ["AAPL"])
        watchlist = _create_watchlist(client, auth_headers)

        res = client.post(
            f"/api/v1/watchlists/{watchlist['id']}/items",
            json={"ticker": "AAPL"},
            headers=auth_headers,
        )
        assert res.status_code == 201
        assert len(res.json()["items"]) == 1
        assert res.json()["items"][0]["ticker"] == "AAPL"
        assert res.json()["items"][0]["data_unavailable"] is False

        res = client.delete(
            f"/api/v1/watchlists/{watchlist['id']}/items/AAPL", headers=auth_headers
        )
        assert res.status_code == 204
        detail = client.get(f"/api/v1/watchlists/{watchlist['id']}", headers=auth_headers)
        assert detail.json()["items"] == []

    def test_adding_the_same_item_twice_is_idempotent(self, client, auth_headers, db_session):
        _ingest(db_session, ["AAPL"])
        watchlist = _create_watchlist(client, auth_headers)
        client.post(
            f"/api/v1/watchlists/{watchlist['id']}/items",
            json={"ticker": "AAPL"},
            headers=auth_headers,
        )
        res = client.post(
            f"/api/v1/watchlists/{watchlist['id']}/items",
            json={"ticker": "AAPL"},
            headers=auth_headers,
        )
        assert len(res.json()["items"]) == 1

    def test_adding_an_unknown_ticker_is_a_404(self, client, auth_headers):
        watchlist = _create_watchlist(client, auth_headers)
        res = client.post(
            f"/api/v1/watchlists/{watchlist['id']}/items",
            json={"ticker": "ZZZZ"},
            headers=auth_headers,
        )
        assert res.status_code == 404


class TestCrossUserOwnershipIsolation:
    def test_user_b_cannot_read_user_as_watchlist(self, client, auth_headers):
        watchlist = _create_watchlist(client, auth_headers, name="Alice's Watchlist")
        b_headers = _second_user_headers(client)
        assert (
            client.get(f"/api/v1/watchlists/{watchlist['id']}", headers=b_headers).status_code
            == 404
        )

    def test_user_b_cannot_add_items_to_user_as_watchlist(self, client, auth_headers, db_session):
        _ingest(db_session, ["AAPL"])
        watchlist = _create_watchlist(client, auth_headers)
        b_headers = _second_user_headers(client)
        res = client.post(
            f"/api/v1/watchlists/{watchlist['id']}/items",
            json={"ticker": "AAPL"},
            headers=b_headers,
        )
        assert res.status_code == 404

    def test_user_b_cannot_delete_user_as_watchlist(self, client, auth_headers):
        watchlist = _create_watchlist(client, auth_headers)
        b_headers = _second_user_headers(client)
        assert (
            client.delete(f"/api/v1/watchlists/{watchlist['id']}", headers=b_headers).status_code
            == 404
        )
        assert (
            client.get(f"/api/v1/watchlists/{watchlist['id']}", headers=auth_headers).status_code
            == 200
        )

    def test_user_bs_watchlist_list_never_includes_user_as(self, client, auth_headers):
        _create_watchlist(client, auth_headers, name="Alice's")
        b_headers = _second_user_headers(client)
        _create_watchlist(client, b_headers, name="Bob's")
        names = [w["name"] for w in client.get("/api/v1/watchlists", headers=b_headers).json()]
        assert names == ["Bob's"]
