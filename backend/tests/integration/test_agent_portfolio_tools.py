"""Integration tests for the Phase 9 read-only agent tools (watchlists,
screener, portfolio, alerts): correct evidence/grounding, ownership
scoping (a tool always resolves within the CURRENT authenticated user —
there is no way to pass another user's id), and the explicit prohibition
that the agent can only read state, never mutate it. All deterministic via
`FakeLLMProvider` — no external LLM credentials required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.agent.conversation import ConversationStore
from app.agent.evidence import EvidenceSourceType
from app.agent.llm_provider import FakeLLMProvider, LLMResponse, ToolCallRequest
from app.agent.orchestrator import run_agent
from app.agent.tools import (
    TOOLS_BY_NAME,
    EmptyInput,
    PortfolioNameInput,
    WatchlistNameInput,
)
from app.db.models.job import JobType
from app.db.models.security import Security
from app.db.models.user import User, UserRole
from app.repositories.job_repository import JobRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.watchlist_repository import WatchlistRepository
from app.services.market_data_service import run_ingestion
from app.services.portfolio_service import create_transaction


def _make_user(db_session, email: str = "portfolio-tools-test@example.com") -> User:
    user = User(
        email=email, password_hash="x", full_name="Portfolio Tools Test", role=UserRole.USER
    )
    db_session.add(user)
    db_session.flush()
    return user


def _seed_security(db_session, ticker: str = "AAPL") -> Security:
    security = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(security)
    db_session.flush()
    return security


def _ingest_prices(db_session, tickers, lookback_days=200) -> None:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback_days)
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()


def _final(text: str) -> LLMResponse:
    return LLMResponse(content=text, tool_calls=(), stop_reason="end_turn")


def _tool_call_response(*calls: ToolCallRequest) -> LLMResponse:
    return LLMResponse(content=None, tool_calls=tuple(calls), stop_reason="tool_use")


class TestGetWatchlistsTool:
    def test_returns_only_the_calling_users_own_watchlists_with_evidence(self, db_session):
        user_a = _make_user(db_session, "a@example.com")
        user_b = _make_user(db_session, "b@example.com")
        WatchlistRepository(db_session).create(
            user_id=user_a.id, name="Alice's List", description=None
        )
        WatchlistRepository(db_session).create(
            user_id=user_b.id, name="Bob's List", description=None
        )
        db_session.flush()

        result = TOOLS_BY_NAME["get_watchlists"].handler(db_session, user_a, EmptyInput())

        names = [w["name"] for w in result.output["watchlists"]]
        assert names == ["Alice's List"]
        assert len(result.evidence) == 1
        assert result.evidence[0].source_type == EvidenceSourceType.WATCHLIST


class TestGetWatchlistTool:
    def test_looking_up_another_users_watchlist_by_name_returns_not_found_not_their_data(
        self, db_session
    ):
        user_a = _make_user(db_session, "a2@example.com")
        user_b = _make_user(db_session, "b2@example.com")
        WatchlistRepository(db_session).create(
            user_id=user_b.id, name="Bob's Secret List", description=None
        )
        db_session.flush()

        result = TOOLS_BY_NAME["get_watchlist"].handler(
            db_session, user_a, WatchlistNameInput(name="Bob's Secret List")
        )
        assert "error" in result.output
        assert result.evidence == []


class TestRunScreenerTool:
    def test_screener_tool_output_matches_the_underlying_service_grounding(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session, "AAPL")
        _ingest_prices(db_session, ["AAPL"])

        from app.agent.tools import ScreenerToolInput

        result = TOOLS_BY_NAME["run_screener"].handler(
            db_session, user, ScreenerToolInput(limit=10)
        )
        assert "error" not in result.output
        tickers = [r["ticker"] for r in result.output["items"]]
        assert "AAPL" in tickers
        assert len(result.evidence) == 1
        assert result.evidence[0].source_type == EvidenceSourceType.SCREENER


class TestPortfolioTools:
    def test_get_portfolio_holdings_matches_the_deterministic_service_computation(self, db_session):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        portfolio = PortfolioRepository(db_session).create(
            user_id=user.id, name="Agent Test Portfolio", description=None, base_currency="USD"
        )
        db_session.flush()
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

        from app.services import portfolio_service

        direct = portfolio_service.get_holdings(db_session, portfolio)

        result = TOOLS_BY_NAME["get_portfolio_holdings"].handler(
            db_session, user, PortfolioNameInput(name="Agent Test Portfolio")
        )
        assert result.output["holdings"][0]["ticker"] == direct[0].ticker
        assert result.output["holdings"][0]["quantity"] == float(direct[0].quantity)

    def test_get_portfolio_performance_reports_the_applications_own_numbers_never_computes_them(
        self, db_session
    ):
        """The tool must be a pure passthrough of `portfolio_service.get_analytics`
        — this is what makes 'the LLM explains, never calculates' true."""
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        portfolio = PortfolioRepository(db_session).create(
            user_id=user.id, name="Perf Portfolio", description=None, base_currency="USD"
        )
        db_session.flush()
        create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(5000), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key=None,
        )

        from app.services import portfolio_service

        direct = portfolio_service.get_analytics(db_session, portfolio)
        result = TOOLS_BY_NAME["get_portfolio_performance"].handler(
            db_session, user, PortfolioNameInput(name="Perf Portfolio")
        )
        assert result.output["cash"] == float(direct.cash)
        assert result.output["realized_pnl"] == float(direct.realized_pnl)

    def test_looking_up_another_users_portfolio_by_name_is_not_found(self, db_session):
        user_a = _make_user(db_session, "porta@example.com")
        user_b = _make_user(db_session, "portb@example.com")
        PortfolioRepository(db_session).create(
            user_id=user_b.id, name="Bob's Portfolio", description=None, base_currency="USD"
        )
        db_session.flush()

        result = TOOLS_BY_NAME["get_portfolio"].handler(
            db_session, user_a, PortfolioNameInput(name="Bob's Portfolio")
        )
        assert "error" in result.output


class TestAgentCannotMutatePortfolioState:
    def test_a_full_conversation_turn_that_reads_holdings_never_writes_any_transaction(
        self, db_session
    ):
        user = _make_user(db_session)
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker])
        portfolio = PortfolioRepository(db_session).create(
            user_id=user.id, name="Read Only Test", description=None, base_currency="USD"
        )
        db_session.flush()
        create_transaction(
            db_session, portfolio, transaction_type="CASH_DEPOSIT", security_id=None,
            quantity=None, price=None, amount=Decimal(1000), fees=Decimal(0), currency=None,
            executed_at=None, idempotency_key=None,
        )
        from app.repositories.transaction_repository import TransactionRepository

        before_count = len(
            TransactionRepository(db_session).list_chronological(portfolio_id=portfolio.id)
        )

        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1",
                        name="get_portfolio_holdings",
                        arguments={"name": "Read Only Test"},
                    )
                ),
                _final("You currently hold no positions in this portfolio. [Portfolio]"),
            ]
        )
        run_agent(
            db_session, user, message="What are my holdings?", conversation_id=None,
            llm_provider=fake, conversation_store=ConversationStore(),
        )

        after_count = len(
            TransactionRepository(db_session).list_chronological(portfolio_id=portfolio.id)
        )
        assert after_count == before_count  # the agent turn wrote nothing
