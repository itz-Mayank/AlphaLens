from datetime import UTC, datetime
from decimal import Decimal

from app.db.models.price_bar import PriceBar
from app.db.models.security import Security
from app.repositories.price_bar_repository import PriceBarRepository


def _security(db_session, ticker: str) -> Security:
    s = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(s)
    db_session.flush()
    return s


def _bar(db_session, security: Security, ts: datetime, close: int) -> None:
    close_d = Decimal(close)
    db_session.add(
        PriceBar(
            security_id=security.id,
            ts=ts,
            open=close_d,
            high=close_d,
            low=close_d,
            close=close_d,
            adjusted_close=close_d,
            volume=100,
        )
    )
    db_session.flush()


def test_get_latest_quotes_prev_close_is_the_immediately_preceding_bar_not_the_first(db_session):
    """With 3+ bars, `prev_close` must come from the second-to-last bar
    chronologically — a regression here (e.g. picking the earliest bar
    instead) would silently corrupt every return calculation."""
    security = _security(db_session, "AAA")
    _bar(db_session, security, datetime(2024, 1, 1, tzinfo=UTC), close=50)
    _bar(db_session, security, datetime(2024, 1, 2, tzinfo=UTC), close=100)
    _bar(db_session, security, datetime(2024, 1, 3, tzinfo=UTC), close=110)

    [row] = PriceBarRepository(db_session).get_latest_quotes()

    assert row.ts == datetime(2024, 1, 3, tzinfo=UTC)
    assert row.close == Decimal(110)
    assert row.prev_close == Decimal(100)  # not 50


def test_get_latest_quotes_is_independent_per_security(db_session):
    a = _security(db_session, "AAA")
    _bar(db_session, a, datetime(2024, 1, 1, tzinfo=UTC), close=10)
    _bar(db_session, a, datetime(2024, 1, 2, tzinfo=UTC), close=12)

    b = _security(db_session, "BBB")
    _bar(db_session, b, datetime(2024, 1, 1, tzinfo=UTC), close=200)
    _bar(db_session, b, datetime(2024, 1, 2, tzinfo=UTC), close=190)

    rows = {row.ticker: row for row in PriceBarRepository(db_session).get_latest_quotes()}

    assert rows["AAA"].close == Decimal(12)
    assert rows["AAA"].prev_close == Decimal(10)
    assert rows["BBB"].close == Decimal(190)
    assert rows["BBB"].prev_close == Decimal(200)


def test_get_latest_quotes_filters_by_security_ids_when_given(db_session):
    a = _security(db_session, "AAA")
    _bar(db_session, a, datetime(2024, 1, 1, tzinfo=UTC), close=10)
    b = _security(db_session, "BBB")
    _bar(db_session, b, datetime(2024, 1, 1, tzinfo=UTC), close=20)

    rows = PriceBarRepository(db_session).get_latest_quotes(security_ids=[a.id])

    assert [r.ticker for r in rows] == ["AAA"]


def test_get_latest_quotes_returns_nothing_for_a_security_with_no_bars(db_session):
    _security(db_session, "NOBARS")

    rows = PriceBarRepository(db_session).get_latest_quotes()

    assert rows == []
