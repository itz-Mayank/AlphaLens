"""Dashboard aggregation tests use hand-crafted securities/price_bars rows
(not the demo provider) so exact expected returns, ties, and edge cases
(insufficient history, mismatched reference dates, all-zero-change) are
fully controlled rather than relying on a random walk's incidental values.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models.price_bar import PriceBar
from app.db.models.security import Security
from app.services.dashboard_service import build_dashboard_overview

DAY1 = datetime(2024, 1, 9, tzinfo=UTC)
DAY2 = datetime(2024, 1, 10, tzinfo=UTC)  # the "as of" / reference date in most tests


def _make_security(db_session, ticker: str, *, sector: str | None = "Technology") -> Security:
    security = Security(
        ticker=ticker,
        name=f"{ticker} Inc.",
        exchange="NASDAQ",
        sector=sector,
        data_source="demo",
    )
    db_session.add(security)
    db_session.flush()
    return security


def _add_bar(
    db_session, security: Security, *, ts: datetime, close: float, volume: int = 1000
) -> None:
    close_d = Decimal(str(close))
    db_session.add(
        PriceBar(
            security_id=security.id,
            ts=ts,
            open=close_d,
            high=close_d,
            low=close_d,
            close=close_d,
            adjusted_close=close_d,
            volume=volume,
        )
    )
    db_session.flush()


class TestNoDataAtAll:
    def test_returns_honest_empty_state(self, db_session):
        overview = build_dashboard_overview(db_session, now=DAY2)

        assert overview.market_summary.total_securities == 0
        assert overview.market_summary.securities_with_price_data == 0
        assert overview.market_summary.latest_market_data_ts is None
        assert overview.market_summary.freshness_status == "no_data"
        assert overview.market_movers.as_of is None
        assert overview.market_movers.top_gainers == []
        assert overview.market_movers.top_losers == []
        assert overview.market_movers.most_active == []
        assert overview.market_breadth.status == "unavailable"
        assert overview.market_breadth.advancing is None
        assert overview.sector_overview.sectors == []
        assert overview.recent_activity == []


class TestMarketSummary:
    def test_counts_securities_with_and_without_price_data(self, db_session):
        with_data = _make_security(db_session, "AAA")
        _add_bar(db_session, with_data, ts=DAY1, close=100)
        _add_bar(db_session, with_data, ts=DAY2, close=105)
        _make_security(db_session, "BBB")  # never ingested

        overview = build_dashboard_overview(db_session, now=DAY2)

        assert overview.market_summary.total_securities == 2
        assert overview.market_summary.securities_with_price_data == 1
        assert overview.market_summary.latest_market_data_ts == DAY2
        assert overview.market_summary.data_sources == ["demo"]


class TestMarketMovers:
    def test_ranks_gainers_and_losers_with_deterministic_tie_break(self, db_session):
        # AAA and BBB both +10% (tie) -> ticker-ascending break, AAA first.
        aaa = _make_security(db_session, "AAA")
        _add_bar(db_session, aaa, ts=DAY1, close=100)
        _add_bar(db_session, aaa, ts=DAY2, close=110, volume=500)

        bbb = _make_security(db_session, "BBB")
        _add_bar(db_session, bbb, ts=DAY1, close=100)
        _add_bar(db_session, bbb, ts=DAY2, close=110, volume=9000)

        ccc = _make_security(db_session, "CCC")
        _add_bar(db_session, ccc, ts=DAY1, close=100)
        _add_bar(db_session, ccc, ts=DAY2, close=80, volume=100)

        overview = build_dashboard_overview(db_session, now=DAY2)

        gainer_tickers = [m.ticker for m in overview.market_movers.top_gainers]
        assert gainer_tickers[:2] == ["AAA", "BBB"]
        assert overview.market_movers.top_gainers[0].change_percent == Decimal("10.000000")

        assert overview.market_movers.top_losers[0].ticker == "CCC"
        assert overview.market_movers.top_losers[0].change_percent == Decimal("-20.000000")

        # most_active ranks by volume, independent of return direction.
        assert overview.market_movers.most_active[0].ticker == "BBB"

    def test_excludes_security_with_only_one_bar_ever(self, db_session):
        only_one_bar = _make_security(db_session, "ONE")
        _add_bar(db_session, only_one_bar, ts=DAY2, close=50)

        has_history = _make_security(db_session, "TWO")
        _add_bar(db_session, has_history, ts=DAY1, close=100)
        _add_bar(db_session, has_history, ts=DAY2, close=101)

        overview = build_dashboard_overview(db_session, now=DAY2)

        gainer_tickers = {m.ticker for m in overview.market_movers.top_gainers}
        loser_tickers = {m.ticker for m in overview.market_movers.top_losers}
        assert "ONE" not in gainer_tickers
        assert "ONE" not in loser_tickers
        # but it's still visible (has data, just no defined return yet):
        active_tickers = {m.ticker for m in overview.market_movers.most_active}
        assert "ONE" in active_tickers
        assert overview.market_breadth.no_data == 1

    def test_excludes_security_whose_latest_bar_predates_the_reference_date(self, db_session):
        stale = _make_security(db_session, "OLD")
        _add_bar(db_session, stale, ts=DAY1 - timedelta(days=1), close=100)
        _add_bar(db_session, stale, ts=DAY1, close=105)  # latest bar is DAY1, not DAY2

        fresh = _make_security(db_session, "NEW")
        _add_bar(db_session, fresh, ts=DAY1, close=100)
        _add_bar(db_session, fresh, ts=DAY2, close=102)

        overview = build_dashboard_overview(db_session, now=DAY2)

        assert overview.market_movers.as_of == DAY2
        mover_tickers = {m.ticker for m in overview.market_movers.top_gainers} | {
            m.ticker for m in overview.market_movers.top_losers
        }
        assert "OLD" not in mover_tickers
        assert "NEW" in mover_tickers
        # OLD still shows up as recently-updated even though it's excluded
        # from movers/breadth/sectors:
        assert "OLD" in {a.ticker for a in overview.recent_activity}


class TestMarketBreadth:
    def test_counts_advancing_declining_and_unchanged(self, db_session):
        up = _make_security(db_session, "UP")
        _add_bar(db_session, up, ts=DAY1, close=100)
        _add_bar(db_session, up, ts=DAY2, close=101)

        down = _make_security(db_session, "DOWN")
        _add_bar(db_session, down, ts=DAY1, close=100)
        _add_bar(db_session, down, ts=DAY2, close=99)

        flat = _make_security(db_session, "FLAT")
        _add_bar(db_session, flat, ts=DAY1, close=100)
        _add_bar(db_session, flat, ts=DAY2, close=100)

        overview = build_dashboard_overview(db_session, now=DAY2)

        breadth = overview.market_breadth
        assert breadth.status == "ok"
        assert breadth.advancing == 1
        assert breadth.declining == 1
        assert breadth.unchanged == 1
        assert breadth.no_data == 0


class TestSectorOverview:
    def test_equal_weighted_average_per_sector(self, db_session):
        tech_a = _make_security(db_session, "TCHA", sector="Technology")
        _add_bar(db_session, tech_a, ts=DAY1, close=100)
        _add_bar(db_session, tech_a, ts=DAY2, close=102)  # +2%

        tech_b = _make_security(db_session, "TCHB", sector="Technology")
        _add_bar(db_session, tech_b, ts=DAY1, close=100)
        _add_bar(db_session, tech_b, ts=DAY2, close=104)  # +4%

        _make_security(db_session, "FING", sector="Financials")  # no price data at all

        overview = build_dashboard_overview(db_session, now=DAY2)

        by_sector = {s.sector: s for s in overview.sector_overview.sectors}
        assert by_sector["Technology"].security_count == 2
        assert by_sector["Technology"].securities_with_data == 2
        assert by_sector["Technology"].average_return_percent == Decimal("3.000000")

        assert by_sector["Financials"].security_count == 1
        assert by_sector["Financials"].securities_with_data == 0
        assert by_sector["Financials"].average_return_percent is None


class TestRecentActivity:
    def test_orders_by_latest_ts_descending_with_ticker_tiebreak(self, db_session):
        older = _make_security(db_session, "OLDER")
        _add_bar(db_session, older, ts=DAY1, close=10)

        newer_b = _make_security(db_session, "BBBB")
        _add_bar(db_session, newer_b, ts=DAY2, close=20)

        newer_a = _make_security(db_session, "AAAA")
        _add_bar(db_session, newer_a, ts=DAY2, close=30)

        overview = build_dashboard_overview(db_session, now=DAY2)

        tickers = [a.ticker for a in overview.recent_activity]
        assert tickers == ["AAAA", "BBBB", "OLDER"]
