"""GET /stocks/discover — live provider-backed security discovery,
distinct from GET /stocks?q= (which only searches already-ingested
securities). The active provider is monkeypatched at the module level
`app.api.v1.stocks.get_market_data_provider` since the endpoint resolves
it directly rather than via FastAPI Depends.
"""

from datetime import date

import app.api.v1.stocks as stocks_module
from app.db.models.job import JobType
from app.providers.base import SecurityInfo
from app.providers.http_client import ProviderRateLimitedError, ProviderResponseError
from app.repositories.job_repository import JobRepository
from app.services.market_data_service import run_ingestion


class _FakeDiscoveryProvider:
    data_source = "external"

    def __init__(self, matches=None, error=None):
        self._matches = matches or []
        self._error = error

    def search_securities(self, query, *, limit=10):
        if self._error:
            raise self._error
        return self._matches[:limit]


def _patch_provider(monkeypatch, provider):
    monkeypatch.setattr(stocks_module, "get_market_data_provider", lambda: provider)


def test_requires_authentication(client):
    res = client.get("/api/v1/stocks/discover?q=AMD")
    assert res.status_code == 401


def test_requires_a_non_empty_query(client, auth_headers):
    res = client.get("/api/v1/stocks/discover?q=", headers=auth_headers)
    assert res.status_code == 422


def test_returns_live_matches_from_the_provider(client, auth_headers, monkeypatch):
    _patch_provider(
        monkeypatch,
        _FakeDiscoveryProvider(
            matches=[SecurityInfo("AMD", "Advanced Micro Devices, Inc.", "NASDAQ", "Technology", "Semiconductors", "USD")]
        ),
    )

    res = client.get("/api/v1/stocks/discover?q=AMD", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body == [
        {
            "ticker": "AMD",
            "name": "Advanced Micro Devices, Inc.",
            "exchange": "NASDAQ",
            "currency": "USD",
            "already_tracked": False,
        }
    ]


def test_flags_a_result_already_ingested_as_already_tracked(client, auth_headers, db_session):
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(
        db_session, job_id=job.id, tickers=["AAPL"], start_date=date(2023, 1, 1), end_date=date(2023, 6, 30)
    )
    db_session.flush()

    res = client.get("/api/v1/stocks/discover?q=AAPL", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()[0]["already_tracked"] is True


def test_provider_rate_limit_maps_to_a_clean_429(client, auth_headers, monkeypatch):
    _patch_provider(
        monkeypatch, _FakeDiscoveryProvider(error=ProviderRateLimitedError("too many requests"))
    )

    res = client.get("/api/v1/stocks/discover?q=AMD", headers=auth_headers)

    assert res.status_code == 429
    assert res.json()["error"]["code"] == "PROVIDER_RATE_LIMITED"


def test_provider_response_error_maps_to_a_clean_503(client, auth_headers, monkeypatch):
    _patch_provider(
        monkeypatch, _FakeDiscoveryProvider(error=ProviderResponseError("malformed response"))
    )

    res = client.get("/api/v1/stocks/discover?q=AMD", headers=auth_headers)

    assert res.status_code == 503
    assert res.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
