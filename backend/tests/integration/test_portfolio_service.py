"""Integration tests for `app/services/portfolio_service.py` against real
Postgres: cash/position validation, idempotency, holdings/analytics
enrichment, and — critically — the no-look-ahead-bias temporal-correctness
of `get_performance_history` (Phase 9's explicit adversarial requirement:
a future transaction or a future price must never move a past point).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.db.models.job import JobType
from app.db.models.security import Security
from app.db.models.user import User, UserRole
from app.repositories.job_repository import JobRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.services import portfolio_service
from app.services.market_data_service import run_ingestion
from app.services.portfolio_service import (
    InsufficientCashError,
    InsufficientPositionError,
    create_transaction,
)


def _make_user(db_session, email: str = "portfolio-test@example.com") -> User:
    user = User(email=email, password_hash="x", full_name="Portfolio Test", role=UserRole.USER)
    db_session.add(user)
    db_session.flush()
    return user


def _seed_security(db_session, ticker: str = "AAPL") -> Security:
    security = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(security)
    db_session.flush()
    return security


def _ingest_prices(db_session, tickers: list[str], *, lookback_days: int = 200) -> None:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback_days)
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()


def _make_portfolio(db_session, user):
    portfolio = PortfolioRepository(db_session).create(
        user_id=user.id, name="Main", description=None, base_currency="USD"
    )
    db_session.flush()
    return portfolio


class TestCashAndPositionValidation:
    def test_a_buy_that_would_overdraw_cash_is_rejected(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        portfolio = _make_portfolio(db_session, user)
        create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(100), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key=None,
        )
        with pytest.raises(InsufficientCashError):
            create_transaction(
                db_session, portfolio, transaction_type="BUY", security_id=security.id,
                quantity=Decimal(10), price=Decimal(100), amount=None, fees=Decimal(0),
                currency=None, executed_at=None, idempotency_key=None,
            )

    def test_selling_more_than_held_is_rejected_long_only(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        portfolio = _make_portfolio(db_session, user)
        create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(10_000), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key=None,
        )
        create_transaction(
            db_session, portfolio, transaction_type="BUY", security_id=security.id,
            quantity=Decimal(5), price=Decimal(100), amount=None, fees=Decimal(0),
            currency=None, executed_at=None, idempotency_key=None,
        )
        with pytest.raises(InsufficientPositionError):
            create_transaction(
                db_session, portfolio, transaction_type="SELL", security_id=security.id,
                quantity=Decimal(6), price=Decimal(100), amount=None, fees=Decimal(0),
                currency=None, executed_at=None, idempotency_key=None,
            )

    def test_a_deposit_then_withdrawal_correctly_affects_available_cash(self, db_session):
        user = _make_user(db_session)
        portfolio = _make_portfolio(db_session, user)
        create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(1000), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key=None,
        )
        create_transaction(
            db_session, portfolio, transaction_type="CASH_WITHDRAWAL", security_id=None,
            quantity=None, price=None, amount=Decimal(400), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key=None,
        )
        analytics = portfolio_service.get_analytics(db_session, portfolio)
        assert analytics.cash == Decimal(600)


class TestIdempotency:
    def test_a_repeated_idempotency_key_returns_the_existing_transaction_not_a_duplicate(
        self, db_session
    ):
        user = _make_user(db_session)
        portfolio = _make_portfolio(db_session, user)
        first = create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(500), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key="dep-1",
        )
        second = create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(500), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key="dep-1",
        )
        assert first.id == second.id
        analytics = portfolio_service.get_analytics(db_session, portfolio)
        assert analytics.cash == Decimal(500)  # not 1000 — no duplicate applied


class TestHoldingsAndAnalytics:
    def test_holdings_reflect_current_price_and_never_fabricate_a_missing_one(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        portfolio = _make_portfolio(db_session, user)
        create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(100_000), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key=None,
        )
        create_transaction(
            db_session, portfolio, transaction_type="BUY", security_id=security.id,
            quantity=Decimal(10), price=Decimal(50), amount=None, fees=Decimal(0),
            currency=None, executed_at=None, idempotency_key=None,
        )
        holdings = portfolio_service.get_holdings(db_session, portfolio)
        assert len(holdings) == 1
        assert holdings[0].last_price is not None  # real ingested price, not fabricated
        assert holdings[0].market_value == holdings[0].quantity * holdings[0].last_price

    def test_a_stock_with_no_price_data_yields_null_market_value_not_zero(self, db_session):
        """A security with a real position but zero ingested price bars —
        the holding's market_value must be None, never a fabricated 0."""
        user = _make_user(db_session)
        security = _seed_security(db_session, ticker="NODATA")
        portfolio = _make_portfolio(db_session, user)
        create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(100_000), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key=None,
        )
        create_transaction(
            db_session, portfolio, transaction_type="BUY", security_id=security.id,
            quantity=Decimal(10), price=Decimal(50), amount=None, fees=Decimal(0),
            currency=None, executed_at=None, idempotency_key=None,
        )
        holdings = portfolio_service.get_holdings(db_session, portfolio)
        assert holdings[0].last_price is None
        assert holdings[0].market_value is None

        analytics = portfolio_service.get_analytics(db_session, portfolio)
        assert analytics.market_value_is_partial is True
        assert analytics.market_value is None
        assert analytics.total_value is None


class TestNoLookAheadBiasPerformanceHistory:
    """Phase 9's explicit adversarial requirement: a future transaction or
    a future price bar must never change a *past* performance point."""

    def test_a_future_transaction_does_not_affect_a_past_performance_point(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        portfolio = _make_portfolio(db_session, user)

        past = datetime.now(UTC) - timedelta(days=100)
        create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(10_000), fees=Decimal(0), currency=None,
            executed_at=past, idempotency_key=None,
        )
        history_before = portfolio_service.get_performance_history(db_session, portfolio)
        assert history_before.available
        past_point_before = next(
            p for p in history_before.points if p.as_of.date() == past.date()
        )

        # A transaction dated "now" (in the future relative to `past`).
        create_transaction(
            db_session, portfolio, transaction_type="CASH_WITHDRAWAL", security_id=None,
            quantity=None, price=None, amount=Decimal(5_000), fees=Decimal(0), currency=None,
            executed_at=datetime.now(UTC), idempotency_key=None,
        )
        history_after = portfolio_service.get_performance_history(db_session, portfolio)
        past_point_after = next(
            p for p in history_after.points if p.as_of.date() == past.date()
        )

        assert past_point_after.cash == past_point_before.cash
        assert past_point_after.net_contributed == past_point_before.net_contributed

    def test_performance_points_use_only_prices_dated_on_or_before_that_point(self, db_session):
        """Directly exercises `_price_as_of`'s bisect logic: a price bar
        dated after a performance point's day must never be used to value
        that day's holding."""
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        portfolio = _make_portfolio(db_session, user)

        earliest_day = datetime.now(UTC) - timedelta(days=150)
        create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(100_000), fees=Decimal(0), currency=None,
            executed_at=earliest_day, idempotency_key=None,
        )
        create_transaction(
            db_session, portfolio, transaction_type="BUY", security_id=security.id,
            quantity=Decimal(10), price=Decimal(50), amount=None, fees=Decimal(0),
            currency=None, executed_at=earliest_day, idempotency_key=None,
        )

        history = portfolio_service.get_performance_history(db_session, portfolio)
        assert history.available

        from app.repositories.price_bar_repository import PriceBarRepository

        all_bars = sorted(
            PriceBarRepository(db_session).get_range(
                security_id=security.id, start=None, end=None
            ),
            key=lambda b: b.ts,
        )

        for point in history.points:
            if point.market_value is None:
                continue
            # The price implied by this point's market_value must come from
            # a bar dated on/before this point's day — never a later one.
            implied_price = point.market_value / Decimal(10)
            bars_on_or_before = [b for b in all_bars if b.ts.date() <= point.as_of.date()]
            assert bars_on_or_before, "a valued point must have had an as-of price bar"
            assert implied_price == bars_on_or_before[-1].close

    def test_no_transactions_yet_reports_unavailable_not_an_empty_fabricated_series(
        self, db_session
    ):
        user = _make_user(db_session)
        portfolio = _make_portfolio(db_session, user)
        history = portfolio_service.get_performance_history(db_session, portfolio)
        assert history.available is False
        assert history.reason is not None
        assert history.points == []


class TestOwnership:
    def test_get_portfolio_for_user_404s_for_another_users_portfolio(self, db_session):
        owner = _make_user(db_session, "owner@example.com")
        stranger = _make_user(db_session, "stranger@example.com")
        portfolio = _make_portfolio(db_session, owner)

        from app.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            portfolio_service.get_portfolio_for_user(
                db_session, portfolio_id=portfolio.id, user_id=stranger.id
            )
