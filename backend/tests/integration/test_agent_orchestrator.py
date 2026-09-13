"""Integration tests for `app/agent/orchestrator.py::run_agent` — the
bounded tool-calling loop. Uses `FakeLLMProvider` exclusively (Step 24: the
full suite must run without external LLM credentials) scripted against
real Postgres-backed tools, so a "tool call" here really executes
`app/agent/tools.py` against seeded data, while the LLM side is fully
deterministic and inspectable via `fake.calls`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.agent.conversation import ConversationStore
from app.agent.llm_provider import FakeLLMProvider, LLMProviderError, LLMResponse, ToolCallRequest
from app.agent.orchestrator import MAX_MESSAGE_LENGTH, AgentError, run_agent
from app.core.config import get_settings
from app.db.models.job import JobType
from app.db.models.security import Security
from app.db.models.user import User, UserRole
from app.repositories.job_repository import JobRepository
from app.services.market_data_service import run_ingestion


def _make_user(db_session, email: str = "orchestrator-test@example.com") -> User:
    user = User(
        email=email,
        password_hash="not-a-real-hash",
        full_name="Orchestrator Test",
        role=UserRole.USER,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _seed_security(db_session, ticker: str = "AAPL", name: str = "Apple Inc.") -> Security:
    security = Security(ticker=ticker, name=name, exchange="NASDAQ", data_source="demo")
    db_session.add(security)
    db_session.flush()
    return security


def _ingest_prices(db_session, tickers: list[str], *, lookback_days: int = 60) -> None:
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


def _tool_call_response(*calls: ToolCallRequest, content: str | None = None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tuple(calls), stop_reason="tool_use")


class TestSingleToolQuestion:
    def test_asks_one_tool_and_returns_a_grounded_answer(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])
        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    )
                ),
                _final("AAPL is currently trading near its latest close. [Market Data]"),
            ]
        )
        store = ConversationStore()

        result = run_agent(
            db_session,
            user,
            message="What's AAPL's current price?",
            conversation_id=None,
            llm_provider=fake,
            conversation_store=store,
        )

        assert result.answer == "AAPL is currently trading near its latest close. [Market Data]"
        assert result.tools_used == ["get_stock_quote"]
        assert len(result.evidence) == 1
        assert result.evidence[0].ticker == "AAPL"
        assert result.iterations == 2
        assert len(result.tool_call_traces) == 1
        assert result.tool_call_traces[0].ok is True
        assert result.model == "fake-model-v1"
        assert result.provider == "fake"
        assert result.conversation_id  # a fresh id was generated


class TestMultiToolQuestion:
    def test_multiple_tool_calls_in_one_turn_are_all_executed(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"], lookback_days=200)
        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    ),
                    ToolCallRequest(
                        id="call_2", name="get_technical_indicators", arguments={"ticker": "AAPL"}
                    ),
                ),
                _final("Here's a combined technical snapshot for AAPL. [Market Data]"),
            ]
        )

        result = run_agent(
            db_session,
            user,
            message="Give me AAPL's price and RSI.",
            conversation_id=None,
            llm_provider=fake,
            conversation_store=ConversationStore(),
        )

        assert set(result.tools_used) == {"get_stock_quote", "get_technical_indicators"}
        assert len(result.tool_call_traces) == 2
        assert all(t.ok for t in result.tool_call_traces)
        assert len(result.evidence) == 2


class TestMultiTurnConversation:
    def test_second_turn_carries_prior_turn_history_for_pronoun_resolution(self, db_session):
        """The orchestrator can't itself "understand" that "it" means AAPL
        — that's the LLM's job. What it must do deterministically is make
        the prior turn available to the LLM on the next call, which this
        verifies via `fake.calls`."""
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])
        store = ConversationStore()
        conv_id = store.new_conversation_id()

        fake_turn_1 = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    )
                ),
                _final("AAPL is trading at its latest price. [Market Data]"),
            ]
        )
        run_agent(
            db_session,
            user,
            message="What's AAPL's price?",
            conversation_id=conv_id,
            llm_provider=fake_turn_1,
            conversation_store=store,
        )

        fake_turn_2 = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(id="call_2", name="get_sentiment", arguments={"ticker": "AAPL"})
                ),
                _final("Sentiment for AAPL is neutral recently. [Sentiment]"),
            ]
        )
        result = run_agent(
            db_session,
            user,
            message="What about its sentiment?",
            conversation_id=conv_id,
            llm_provider=fake_turn_2,
            conversation_store=store,
        )

        assert result.conversation_id == conv_id
        first_call_messages = fake_turn_2.calls[0]["messages"]
        message_texts = [m.content for m in first_call_messages if m.content]
        assert any("What's AAPL's price?" in text for text in message_texts)
        assert any("AAPL is trading at its latest price" in text for text in message_texts)
        assert any("What about its sentiment?" in text for text in message_texts)


class TestHonestHandlingOfMissingData:
    def test_unknown_ticker_is_reported_honestly_not_fabricated(self, db_session):
        user = _make_user(db_session)
        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_stock_quote", arguments={"ticker": "ZZZZ"}
                    )
                ),
                _final("ZZZZ isn't a ticker tracked by this deployment, so I can't quote it."),
            ]
        )

        result = run_agent(
            db_session,
            user,
            message="What's ZZZZ's price?",
            conversation_id=None,
            llm_provider=fake,
            conversation_store=ConversationStore(),
        )

        assert "isn't a ticker" in result.answer
        assert result.tools_used == []  # the failed call is never credited as evidence
        assert result.evidence == []
        assert result.tool_call_traces[0].ok is False

    def test_insufficient_history_is_reported_honestly(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"], lookback_days=5)
        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_technical_indicators", arguments={"ticker": "AAPL"}
                    )
                ),
                _final("I don't have enough price history yet to compute indicators for AAPL."),
            ]
        )

        result = run_agent(
            db_session,
            user,
            message="What's AAPL's RSI?",
            conversation_id=None,
            llm_provider=fake,
            conversation_store=ConversationStore(),
        )

        assert "don't have enough" in result.answer
        assert result.evidence == []


class TestToolFailureIsHandledGracefully:
    def test_an_unexpected_exception_inside_a_tool_does_not_crash_the_loop(
        self, db_session, monkeypatch
    ):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])

        def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated unexpected failure")

        monkeypatch.setattr("app.agent.tools.compute_quote", _boom)

        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    )
                ),
                _final("I ran into a problem retrieving AAPL's quote just now."),
            ]
        )

        result = run_agent(
            db_session,
            user,
            message="What's AAPL's price?",
            conversation_id=None,
            llm_provider=fake,
            conversation_store=ConversationStore(),
        )

        assert result.tool_call_traces[0].ok is False
        assert result.evidence == []
        assert "problem retrieving" in result.answer


class TestLLMProviderFailure:
    def test_a_scripted_provider_error_becomes_a_clean_agent_error(self, db_session):
        user = _make_user(db_session)
        fake = FakeLLMProvider([LLMProviderError("simulated timeout")])

        with pytest.raises(AgentError, match="temporarily unavailable"):
            run_agent(
                db_session,
                user,
                message="What's AAPL's price?",
                conversation_id=None,
                llm_provider=fake,
                conversation_store=ConversationStore(),
            )


class TestMaxIterationsBound:
    def test_exhausting_the_iteration_budget_produces_a_controlled_fallback(
        self, db_session, monkeypatch
    ):
        settings = get_settings()
        monkeypatch.setattr(settings, "llm_max_tool_iterations", 2)
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])
        # Scripts more tool-call turns than the iteration budget allows —
        # the LLM never gets to produce a final answer.
        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    )
                ),
                _tool_call_response(
                    ToolCallRequest(
                        id="call_2", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    )
                ),
            ]
        )

        result = run_agent(
            db_session,
            user,
            message="Keep looking things up.",
            conversation_id=None,
            llm_provider=fake,
            conversation_store=ConversationStore(),
        )

        assert "too many steps" in result.answer or "allotted number of steps" in result.answer
        assert result.iterations == 2

    def test_a_turn_requesting_more_tool_calls_than_the_per_turn_cap_only_runs_the_cap(
        self, db_session, monkeypatch
    ):
        settings = get_settings()
        monkeypatch.setattr(settings, "llm_max_tool_calls_per_turn", 1)
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])
        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    ),
                    ToolCallRequest(
                        id="call_2", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    ),
                    ToolCallRequest(
                        id="call_3", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    ),
                ),
                _final("Done."),
            ]
        )

        result = run_agent(
            db_session,
            user,
            message="Look this up a few times.",
            conversation_id=None,
            llm_provider=fake,
            conversation_store=ConversationStore(),
        )

        assert len(result.tool_call_traces) == 1


class TestHallucinatedOrMalformedToolCalls:
    def test_an_unknown_tool_name_is_handled_without_crashing(self, db_session):
        user = _make_user(db_session)
        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_unicorn_data", arguments={"ticker": "AAPL"}
                    )
                ),
                _final("I don't have a tool for that request."),
            ]
        )

        result = run_agent(
            db_session,
            user,
            message="Tell me about unicorns.",
            conversation_id=None,
            llm_provider=fake,
            conversation_store=ConversationStore(),
        )

        assert result.tool_call_traces[0].name == "get_unicorn_data"
        assert result.tool_call_traces[0].ok is False
        assert result.tools_used == []
        assert "don't have a tool" in result.answer

    def test_malformed_arguments_are_handled_without_crashing(self, db_session):
        user = _make_user(db_session)
        fake = FakeLLMProvider(
            [
                _tool_call_response(
                    ToolCallRequest(
                        id="call_1", name="get_stock_quote", arguments={"not_a_ticker": 123}
                    )
                ),
                _final("I couldn't understand which ticker you meant."),
            ]
        )

        result = run_agent(
            db_session,
            user,
            message="What's the price?",
            conversation_id=None,
            llm_provider=fake,
            conversation_store=ConversationStore(),
        )

        assert result.tool_call_traces[0].ok is False
        assert result.tools_used == []
        assert "couldn't understand" in result.answer


class TestMessageValidation:
    def test_oversized_message_is_rejected(self, db_session):
        user = _make_user(db_session)
        fake = FakeLLMProvider([_final("unused")])

        with pytest.raises(AgentError, match="too long"):
            run_agent(
                db_session,
                user,
                message="x" * (MAX_MESSAGE_LENGTH + 1),
                conversation_id=None,
                llm_provider=fake,
                conversation_store=ConversationStore(),
            )

    def test_empty_message_is_rejected(self, db_session):
        user = _make_user(db_session)
        fake = FakeLLMProvider([_final("unused")])

        with pytest.raises(AgentError, match="empty"):
            run_agent(
                db_session,
                user,
                message="   ",
                conversation_id=None,
                llm_provider=fake,
                conversation_store=ConversationStore(),
            )
