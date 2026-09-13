from datetime import UTC, datetime
from decimal import Decimal

from app.db.models.price_bar import PriceBar
from app.db.models.security import Security


def _seed_one_security_with_two_bars(db_session) -> None:
    security = Security(
        ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", sector="Technology", data_source="demo"
    )
    db_session.add(security)
    db_session.flush()
    for ts, close in [
        (datetime(2024, 1, 9, tzinfo=UTC), Decimal(100)),
        (datetime(2024, 1, 10, tzinfo=UTC), Decimal(105)),
    ]:
        db_session.add(
            PriceBar(
                security_id=security.id,
                ts=ts,
                open=close,
                high=close,
                low=close,
                close=close,
                adjusted_close=close,
                volume=1000,
            )
        )
    db_session.flush()


def test_dashboard_overview_requires_authentication(client):
    res = client.get("/api/v1/dashboard/overview")
    assert res.status_code == 401


def test_dashboard_overview_empty_state_before_any_ingestion(client, auth_headers):
    res = client.get("/api/v1/dashboard/overview", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["market_summary"]["total_securities"] == 0
    assert body["market_summary"]["freshness_status"] == "no_data"
    assert body["market_movers"]["top_gainers"] == []
    assert body["market_breadth"]["status"] == "unavailable"
    assert body["sector_overview"]["sectors"] == []
    assert body["recent_activity"] == []


def test_dashboard_overview_reflects_real_data(client, auth_headers, db_session):
    _seed_one_security_with_two_bars(db_session)

    res = client.get("/api/v1/dashboard/overview", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["market_summary"]["total_securities"] == 1
    assert body["market_summary"]["securities_with_price_data"] == 1
    assert body["market_summary"]["data_sources"] == ["demo"]
    assert body["market_movers"]["top_gainers"][0]["ticker"] == "AAPL"
    assert Decimal(body["market_movers"]["top_gainers"][0]["change_percent"]) == Decimal(5)
    assert body["market_breadth"]["status"] == "ok"
    assert body["market_breadth"]["advancing"] == 1
    assert body["sector_overview"]["sectors"][0]["sector"] == "Technology"
    assert body["recent_activity"][0]["ticker"] == "AAPL"


def test_dashboard_overview_is_cached(client, auth_headers, db_session):
    """A change made after the first request shouldn't appear in the
    second, within the cache TTL — proves the cache is actually being
    read, not just written to."""
    res1 = client.get("/api/v1/dashboard/overview", headers=auth_headers)
    assert res1.json()["market_summary"]["total_securities"] == 0

    _seed_one_security_with_two_bars(db_session)

    res2 = client.get("/api/v1/dashboard/overview", headers=auth_headers)
    assert res2.json()["market_summary"]["total_securities"] == 0  # still cached

    from app.core.cache import get_redis_client

    get_redis_client().flushdb()

    res3 = client.get("/api/v1/dashboard/overview", headers=auth_headers)
    assert res3.json()["market_summary"]["total_securities"] == 1
