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


def test_list_stocks_requires_authentication(client):
    res = client.get("/api/v1/stocks")
    assert res.status_code == 401


def test_list_stocks_empty_before_any_ingestion(client, auth_headers):
    res = client.get("/api/v1/stocks", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_stocks_returns_items_with_computed_quote(client, auth_headers, db_session):
    _ingest(db_session, ["AAPL"])

    res = client.get("/api/v1/stocks", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["ticker"] == "AAPL"
    assert item["data_source"] == "demo"
    assert item["last_price"] is not None
    assert item["change"] is not None
    assert item["as_of"] is not None


def test_list_stocks_search_by_ticker_or_name(client, auth_headers, db_session):
    _ingest(db_session, ["AAPL", "MSFT"])

    by_ticker = client.get("/api/v1/stocks?q=AAPL", headers=auth_headers).json()
    assert [i["ticker"] for i in by_ticker["items"]] == ["AAPL"]

    by_name = client.get("/api/v1/stocks?q=Microsoft", headers=auth_headers).json()
    assert [i["ticker"] for i in by_name["items"]] == ["MSFT"]


def test_list_stocks_filters_by_sector(client, auth_headers, db_session):
    _ingest(db_session, ["AAPL", "JPM"])  # Technology vs Financials

    res = client.get("/api/v1/stocks?sector=Financials", headers=auth_headers).json()

    assert [i["ticker"] for i in res["items"]] == ["JPM"]


def test_list_stocks_pagination(client, auth_headers, db_session):
    _ingest(db_session, ["AAPL", "MSFT", "GOOGL"])

    page1 = client.get("/api/v1/stocks?limit=2&offset=0", headers=auth_headers).json()
    page2 = client.get("/api/v1/stocks?limit=2&offset=2", headers=auth_headers).json()

    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1
    assert {i["ticker"] for i in page1["items"]} != {i["ticker"] for i in page2["items"]}


def test_get_stock_detail_includes_52_week_range(client, auth_headers, db_session):
    _ingest(db_session, ["AAPL"], start=date(2023, 1, 1), end=date(2023, 12, 31))

    res = client.get("/api/v1/stocks/AAPL", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["ticker"] == "AAPL"
    assert body["week_52_high"] is not None
    assert body["week_52_low"] is not None
    assert float(body["week_52_low"]) <= float(body["last_price"]) <= float(body["week_52_high"])


def test_get_stock_detail_is_case_insensitive(client, auth_headers, db_session):
    _ingest(db_session, ["AAPL"])

    res = client.get("/api/v1/stocks/aapl", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["ticker"] == "AAPL"


def test_get_stock_detail_404_for_unknown_ticker(client, auth_headers):
    res = client.get("/api/v1/stocks/NOTATICKER", headers=auth_headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "STOCK_NOT_FOUND"


def test_get_stock_prices_returns_bars_ordered_ascending(client, auth_headers, db_session):
    _ingest(db_session, ["AAPL"], start=date(2023, 1, 1), end=date(2023, 1, 31))

    res = client.get("/api/v1/stocks/AAPL/prices?range=MAX", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["data_source"] == "demo"
    timestamps = [bar["ts"] for bar in body["bars"]]
    assert timestamps == sorted(timestamps)
    assert len(body["bars"]) > 15


def test_get_stock_prices_range_filters_the_window(client, auth_headers, db_session):
    # Range filters (1M/3M/etc.) are anchored to wall-clock "now", so the
    # ingested window must reach up to today for a "1M" filter to overlap
    # it at all — end=None (the production default) does exactly that.
    _ingest(db_session, ["AAPL"], start=date(2023, 1, 1), end=None)

    full = client.get("/api/v1/stocks/AAPL/prices?range=MAX", headers=auth_headers).json()
    one_month = client.get("/api/v1/stocks/AAPL/prices?range=1M", headers=auth_headers).json()

    assert 0 < len(one_month["bars"]) < len(full["bars"])


def test_get_stock_prices_404_for_unknown_ticker(client, auth_headers):
    res = client.get("/api/v1/stocks/NOTATICKER/prices", headers=auth_headers)
    assert res.status_code == 404


class TestFundamentals:
    def test_404_for_an_unknown_ticker(self, client, auth_headers):
        res = client.get("/api/v1/stocks/NOTATICKER/fundamentals", headers=auth_headers)
        assert res.status_code == 404

    def test_reports_unavailable_for_a_tracked_security_with_no_fundamentals_ingested(
        self, client, auth_headers, db_session
    ):
        """Demo Mode / no fundamentals provider configured must never
        fabricate a value — a tracked security with nothing ingested
        reports `available=False`, not a fake P/E or balance-sheet figure."""
        _ingest(db_session, ["AAPL"])

        res = client.get("/api/v1/stocks/AAPL/fundamentals", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["ticker"] == "AAPL"
        assert body["available"] is False
        assert body["facts"] == []

    def test_returns_ingested_facts_with_provenance(self, client, auth_headers, db_session):
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from app.providers.base import CompanyFactsResult, FundamentalFact
        from app.repositories.fundamentals_repository import FundamentalsRepository
        from app.repositories.security_repository import SecurityRepository

        _ingest(db_session, ["AAPL"])
        security = SecurityRepository(db_session).get_by_ticker("AAPL")
        FundamentalsRepository(db_session).upsert_facts(
            security_id=security.id,
            result=CompanyFactsResult(
                ticker="AAPL", company_name="Apple Inc.", external_id="CIK0000320193",
                facts=[
                    FundamentalFact(
                        concept="Assets", value=Decimal(100), unit="USD", period_start=None,
                        period_end=date(2023, 9, 30), fiscal_year=2023, fiscal_period="FY",
                        form="10-K", filed_date=date(2023, 11, 3), accession_number="acc-1",
                    )
                ],
                retrieved_at=datetime.now(UTC),
            ),
            source="SECEdgarFundamentalsProvider",
            retrieved_at=datetime.now(UTC),
        )
        db_session.flush()

        res = client.get("/api/v1/stocks/AAPL/fundamentals", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["available"] is True
        assert body["source"] == "SECEdgarFundamentalsProvider"
        assert body["retrieved_at"] is not None
        assert body["facts"][0]["concept"] == "Assets"
        assert body["facts"][0]["value"] == "100.0000"  # Numeric(24, 4) column precision
