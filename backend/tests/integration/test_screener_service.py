"""Integration tests for `app/services/screener_service.py`: deterministic
pagination, and the explicit Phase 9 requirement that missing forecast/
sentiment/return data is reported as null, never fabricated as zero.
"""

from __future__ import annotations

from datetime import date

from app.db.models.job import JobType
from app.db.models.security import Security
from app.repositories.job_repository import JobRepository
from app.services.market_data_service import run_ingestion
from app.services.screener_service import ScreenerFilters, run_screener


def _ingest(db_session, tickers, start=date(2023, 1, 1), end=date(2023, 6, 30)):
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()


def _seed_security(db_session, ticker: str, sector: str | None = None) -> Security:
    security = Security(
        ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo", sector=sector
    )
    db_session.add(security)
    db_session.flush()
    return security


class TestMissingDataIsNullNeverZero:
    def test_a_security_with_no_price_bars_has_null_price_fields_not_zero(self, db_session):
        _seed_security(db_session, "NODATA")
        result = run_screener(db_session, ScreenerFilters())
        row = next(r for r in result.items if r.ticker == "NODATA")
        assert row.last_price is None
        assert row.change_percent is None
        assert "last_price" in row.unavailable_fields

    def test_insufficient_history_for_20d_return_is_null_not_zero(self, db_session):
        _seed_security(db_session, "SHORTHIST")
        _ingest(db_session, ["SHORTHIST"], start=date(2023, 1, 1), end=date(2023, 1, 10))
        result = run_screener(db_session, ScreenerFilters())
        row = next(r for r in result.items if r.ticker == "SHORTHIST")
        assert row.return_20d_percent is None
        assert "return_20d_percent" in row.unavailable_fields

    def test_a_ticker_outside_the_forecast_universe_has_a_null_forecast_direction(self, db_session):
        _seed_security(db_session, "NOTINMODEL")
        _ingest(db_session, ["NOTINMODEL"])
        result = run_screener(db_session, ScreenerFilters())
        row = next(r for r in result.items if r.ticker == "NOTINMODEL")
        assert row.forecast_direction is None
        assert "forecast_direction" in row.unavailable_fields

    def test_filtering_by_forecast_direction_excludes_rows_with_no_forecast_rather_than_matching(
        self, db_session
    ):
        _seed_security(db_session, "NOFORECAST")
        _ingest(db_session, ["NOFORECAST"])
        result = run_screener(db_session, ScreenerFilters(forecast_direction="Bullish"))
        assert all(r.ticker != "NOFORECAST" for r in result.items)


class TestDeterministicPagination:
    def test_the_same_filters_and_page_always_return_the_same_rows_in_the_same_order(
        self, db_session
    ):
        for ticker in ["AAA", "BBB", "CCC", "DDD", "EEE"]:
            _seed_security(db_session, ticker)

        first = run_screener(db_session, ScreenerFilters(limit=2, offset=0))
        second = run_screener(db_session, ScreenerFilters(limit=2, offset=0))
        assert [r.ticker for r in first.items] == [r.ticker for r in second.items]
        assert [r.ticker for r in first.items] == ["AAA", "BBB"]

    def test_pages_do_not_overlap_or_skip_rows(self, db_session):
        for ticker in ["AAA", "BBB", "CCC", "DDD", "EEE"]:
            _seed_security(db_session, ticker)

        page1 = run_screener(db_session, ScreenerFilters(limit=2, offset=0))
        page2 = run_screener(db_session, ScreenerFilters(limit=2, offset=2))
        page3 = run_screener(db_session, ScreenerFilters(limit=2, offset=4))

        all_tickers = [r.ticker for r in page1.items] + [r.ticker for r in page2.items] + [
            r.ticker for r in page3.items
        ]
        assert all_tickers == ["AAA", "BBB", "CCC", "DDD", "EEE"]
        assert page1.total == page2.total == page3.total == 5

    def test_sorting_by_a_field_with_ties_still_breaks_ties_by_ticker_deterministically(
        self, db_session
    ):
        # None of these have price data, so change_percent is None for all —
        # a pure tie on the sort key.
        for ticker in ["ZZZ", "AAA", "MMM"]:
            _seed_security(db_session, ticker)
        result = run_screener(db_session, ScreenerFilters(sort_by="change_percent", limit=10))
        assert [r.ticker for r in result.items] == ["AAA", "MMM", "ZZZ"]


class TestSectorAndQueryFilters:
    def test_sector_filter_narrows_the_universe(self, db_session):
        _seed_security(db_session, "TECH1", sector="Technology")
        _seed_security(db_session, "FIN1", sector="Financials")
        result = run_screener(db_session, ScreenerFilters(sector="Technology"))
        assert [r.ticker for r in result.items] == ["TECH1"]
