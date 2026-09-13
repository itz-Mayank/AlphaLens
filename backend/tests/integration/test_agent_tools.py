"""Integration tests for `app/agent/tools.py` — every tool wraps an
existing Phase 5-7 service, so these run against real Postgres and real
(not mocked) demo-provider data, same conventions as
`tests/api/test_forecast.py`/`test_stock_news.py`.

Registry-independent tools (quote, price history, indicators, news,
sentiment, sentiment history) are tested unconditionally. The three tools
backed by the trained ML model registry (forecast, forecast explanation,
backtest) are skipped — not failed — when no registry exists, matching
`test_forecast.py`'s `_REGISTRY_EXISTS` pattern.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.agent.evidence import EvidenceSourceType
from app.agent.tools import (
    TOOLS,
    TOOLS_BY_NAME,
    BacktestInput,
    ForecastExplanationInput,
    NewsInput,
    PriceHistoryInput,
    SentimentHistoryInput,
    TickerInput,
)
from app.core.config import get_settings
from app.db.models.job import JobType
from app.db.models.security import Security
from app.db.models.user import User, UserRole
from app.repositories.job_repository import JobRepository
from app.services.market_data_service import run_ingestion
from app.services.news_sentiment_service import run_news_ingestion
from pydantic import ValidationError

_REGISTRY_EXISTS = Path(get_settings().ml_registry_path).exists()


def _make_user(db_session) -> User:
    user = User(
        email="agent-tools-test@example.com",
        password_hash="not-a-real-hash",
        full_name="Agent Tools Test",
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


def _ingest_prices(db_session, tickers: list[str], *, lookback_days: int = 200) -> None:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback_days)
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()


def _ingest_news(db_session, tickers: list[str], since_days: int = 7) -> None:
    job = JobRepository(db_session).create(
        job_type=JobType.NEWS_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    since = datetime.now(UTC) - timedelta(days=since_days)
    run_news_ingestion(db_session, job_id=job.id, tickers=tickers, since=since)
    db_session.flush()


class TestToolRegistry:
    def test_nineteen_tools_are_registered(self):
        """9 Phase 5-8 tools + 7 Phase 9 read-only tools (watchlists,
        screener, portfolio, alerts) + 3 Phase 10 provider-ecosystem
        read-only tools (fundamentals, macro, data-source status) — see
        docs/decisions.md's Phase 9/10 ADRs."""
        assert len(TOOLS) == 19

    def test_every_tool_is_looked_up_by_name(self):
        assert set(TOOLS_BY_NAME) == {t.name for t in TOOLS}

    def test_every_tool_definition_has_a_valid_json_schema(self):
        for tool in TOOLS:
            definition = tool.definition()
            assert definition.name == tool.name
            assert definition.description
            assert definition.input_schema["type"] == "object"

    def test_no_arbitrary_code_execution_tools_exist(self):
        """Structural security boundary (Step 8): the tool registry must
        never grow an execute_sql/execute_python/execute_shell/filesystem
        escape hatch."""
        forbidden = {"execute_sql", "execute_python", "execute_shell", "read_file", "write_file"}
        assert forbidden.isdisjoint(TOOLS_BY_NAME)

    def test_no_portfolio_mutating_tools_exist(self):
        """Phase 9's explicit prohibition: the agent may only ever read
        portfolio/watchlist/alert state via deterministic services, never
        mutate it (see app/agent/tools.py's module docstring)."""
        forbidden = {
            "execute_trade", "place_order", "buy_stock", "sell_stock",
            "modify_portfolio", "delete_portfolio", "create_transaction",
            "delete_watchlist", "delete_alert", "create_alert",
        }
        assert forbidden.isdisjoint(TOOLS_BY_NAME)


class TestGetStockQuote:
    def test_unknown_ticker_returns_a_structured_error_not_an_exception(self, db_session):
        user = _make_user(db_session)
        result = TOOLS_BY_NAME["get_stock_quote"].handler(
            db_session, user, TickerInput(ticker="ZZZZ")
        )
        assert "error" in result.output
        assert result.evidence == []

    def test_known_ticker_with_no_price_data_yet_returns_a_structured_error(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        result = TOOLS_BY_NAME["get_stock_quote"].handler(
            db_session, user, TickerInput(ticker="AAPL")
        )
        assert "error" in result.output
        assert result.evidence == []

    def test_real_quote_produces_market_data_evidence(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])

        result = TOOLS_BY_NAME["get_stock_quote"].handler(
            db_session, user, TickerInput(ticker="AAPL")
        )

        assert "error" not in result.output
        assert result.output["ticker"] == "AAPL"
        assert isinstance(result.output["last_price"], float)
        assert len(result.evidence) == 1
        evidence = result.evidence[0]
        assert evidence.source_type == EvidenceSourceType.MARKET_DATA
        assert evidence.ticker == "AAPL"
        assert evidence.data == result.output
        assert evidence.provenance == "demo"

    def test_ticker_is_case_insensitive(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])

        result = TOOLS_BY_NAME["get_stock_quote"].handler(
            db_session, user, TickerInput(ticker="aapl")
        )

        assert result.output["ticker"] == "AAPL"


class TestGetPriceHistory:
    def test_unknown_ticker(self, db_session):
        user = _make_user(db_session)
        result = TOOLS_BY_NAME["get_price_history"].handler(
            db_session, user, PriceHistoryInput(ticker="ZZZZ", days=30)
        )
        assert "error" in result.output

    def test_no_history_available(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        result = TOOLS_BY_NAME["get_price_history"].handler(
            db_session, user, PriceHistoryInput(ticker="AAPL", days=30)
        )
        assert "error" in result.output
        assert result.evidence == []

    def test_real_history_is_summarized_not_a_raw_dump(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])

        result = TOOLS_BY_NAME["get_price_history"].handler(
            db_session, user, PriceHistoryInput(ticker="AAPL", days=60)
        )

        assert "error" not in result.output
        output = result.output
        assert set(output) == {
            "ticker",
            "days",
            "num_bars",
            "start_date",
            "end_date",
            "start_price",
            "end_price",
            "high",
            "low",
            "cumulative_return_percent",
            "data_source",
        }
        assert "daily_bars" not in output  # controlled context: no raw array
        assert output["num_bars"] > 0
        assert len(result.evidence) == 1
        assert result.evidence[0].source_type == EvidenceSourceType.MARKET_DATA


class TestGetTechnicalIndicators:
    def test_unknown_ticker(self, db_session):
        user = _make_user(db_session)
        result = TOOLS_BY_NAME["get_technical_indicators"].handler(
            db_session, user, TickerInput(ticker="ZZZZ")
        )
        assert "error" in result.output

    def test_insufficient_history_returns_a_structured_error(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"], lookback_days=10)

        result = TOOLS_BY_NAME["get_technical_indicators"].handler(
            db_session, user, TickerInput(ticker="AAPL")
        )

        assert "error" in result.output
        assert result.evidence == []

    def test_real_indicators_are_computed_and_evidenced(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"], lookback_days=200)

        result = TOOLS_BY_NAME["get_technical_indicators"].handler(
            db_session, user, TickerInput(ticker="AAPL")
        )

        assert "error" not in result.output
        indicators = result.output["indicators"]
        for key in ("sma_20", "ema_12", "rsi_14", "macd_line", "atr_14"):
            assert isinstance(indicators[key], float)
        assert len(result.evidence) == 1
        assert result.evidence[0].source_type == EvidenceSourceType.MARKET_DATA


class TestGetNews:
    def test_unknown_ticker(self, db_session):
        user = _make_user(db_session)
        result = TOOLS_BY_NAME["get_news"].handler(
            db_session, user, NewsInput(ticker="ZZZZ", limit=5)
        )
        assert "error" in result.output

    def test_no_articles_yet_returns_empty_not_an_error(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)

        result = TOOLS_BY_NAME["get_news"].handler(
            db_session, user, NewsInput(ticker="AAPL", limit=5)
        )

        assert "error" not in result.output
        assert result.output["articles"] == []
        assert result.evidence == []

    def test_real_articles_produce_news_evidence_with_real_urls(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_news(db_session, ["AAPL"])

        result = TOOLS_BY_NAME["get_news"].handler(
            db_session, user, NewsInput(ticker="AAPL", limit=5)
        )

        assert 0 < len(result.output["articles"]) <= 5
        assert len(result.evidence) == len(result.output["articles"])
        for evidence in result.evidence:
            assert evidence.source_type == EvidenceSourceType.NEWS
            assert evidence.ticker == "AAPL"
            assert evidence.provenance.startswith("https://")  # never fabricated

    def test_limit_is_respected(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_news(db_session, ["AAPL"])

        result = TOOLS_BY_NAME["get_news"].handler(
            db_session, user, NewsInput(ticker="AAPL", limit=1)
        )

        assert len(result.output["articles"]) <= 1


class TestGetSentiment:
    def test_unknown_ticker(self, db_session):
        user = _make_user(db_session)
        result = TOOLS_BY_NAME["get_sentiment"].handler(
            db_session, user, TickerInput(ticker="ZZZZ")
        )
        assert "error" in result.output

    def test_no_articles_yet_still_produces_a_structured_zero_result(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)

        result = TOOLS_BY_NAME["get_sentiment"].handler(
            db_session, user, TickerInput(ticker="AAPL")
        )

        assert "error" not in result.output
        assert result.output["last_7d"]["article_count"] == 0
        assert len(result.evidence) == 1
        assert result.evidence[0].source_type == EvidenceSourceType.SENTIMENT

    def test_real_sentiment_reflects_ingested_articles(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_news(db_session, ["AAPL"])

        result = TOOLS_BY_NAME["get_sentiment"].handler(
            db_session, user, TickerInput(ticker="AAPL")
        )

        assert result.output["last_7d"]["article_count"] > 0
        assert result.evidence[0].data == result.output


class TestGetSentimentHistory:
    def test_unknown_ticker(self, db_session):
        user = _make_user(db_session)
        result = TOOLS_BY_NAME["get_sentiment_history"].handler(
            db_session, user, SentimentHistoryInput(ticker="ZZZZ", days=14)
        )
        assert "error" in result.output

    def test_returns_requested_number_of_points(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)

        result = TOOLS_BY_NAME["get_sentiment_history"].handler(
            db_session, user, SentimentHistoryInput(ticker="AAPL", days=10)
        )

        assert "error" not in result.output
        assert len(result.output["points"]) == 10
        assert len(result.evidence) == 1
        assert result.evidence[0].source_type == EvidenceSourceType.SENTIMENT


@pytest.mark.skipif(
    not _REGISTRY_EXISTS, reason="no trained model registry - run the real experiment first"
)
class TestGetForecastWithRealModels:
    def test_unsupported_ticker_returns_a_structured_error(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session, ticker="TSLA", name="Tesla Inc.")
        _ingest_prices(db_session, ["TSLA"])

        result = TOOLS_BY_NAME["get_forecast"].handler(db_session, user, TickerInput(ticker="TSLA"))

        assert "error" in result.output
        assert result.evidence == []

    def test_real_forecast_produces_forecast_evidence(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])

        result = TOOLS_BY_NAME["get_forecast"].handler(db_session, user, TickerInput(ticker="AAPL"))

        assert "error" not in result.output
        assert result.output["ticker"] == "AAPL"
        assert result.output["predicted_direction"] in {"Bearish", "Neutral", "Bullish"}
        assert len(result.evidence) == 1
        evidence = result.evidence[0]
        assert evidence.source_type == EvidenceSourceType.FORECAST
        assert evidence.data == result.output


@pytest.mark.skipif(
    not _REGISTRY_EXISTS, reason="no trained model registry - run the real experiment first"
)
class TestGetForecastExplanationWithRealModels:
    def test_top_n_is_respected_and_produces_shap_evidence(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        _ingest_prices(db_session, ["AAPL"])

        result = TOOLS_BY_NAME["get_forecast_explanation"].handler(
            db_session, user, ForecastExplanationInput(ticker="AAPL", top_n=3)
        )

        assert "error" not in result.output
        assert len(result.output["top_direction_factors"]) == 3
        assert len(result.evidence) == 1
        evidence = result.evidence[0]
        assert evidence.source_type == EvidenceSourceType.SHAP
        # "SHAP" not "Shap" — this is what the LLM would cite inline.
        assert evidence.citation_tag() == "[SHAP]"


@pytest.mark.skipif(
    not _REGISTRY_EXISTS, reason="no trained model registry - run the real experiment first"
)
class TestRunBacktestWithRealModels:
    def test_real_backtest_strips_the_equity_curve_from_llm_facing_output(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session, ticker="AAPL", name="Apple Inc.")
        _seed_security(db_session, ticker="MSFT", name="Microsoft Corp.")
        _ingest_prices(db_session, ["AAPL", "MSFT"])
        end = datetime.now(UTC).date()
        start = end - timedelta(days=180)

        result = TOOLS_BY_NAME["run_backtest"].handler(
            db_session,
            user,
            BacktestInput(tickers=["AAPL", "MSFT"], start_date=start, end_date=end),
        )

        assert "error" not in result.output
        assert "equity_curve" not in result.output  # controlled context (Step 14)
        assert result.output["equity_curve_points"] > 0
        assert isinstance(result.output["metrics"]["cumulative_return"], float)
        assert len(result.evidence) == 1
        evidence = result.evidence[0]
        assert evidence.source_type == EvidenceSourceType.BACKTEST
        assert evidence.ticker is None  # portfolio-level, not single-ticker
        assert "equity_curve" not in evidence.data

    def test_too_many_tickers_is_rejected_at_the_schema_level(self):
        with pytest.raises(ValidationError):
            BacktestInput(
                tickers=[f"T{i}" for i in range(10)],
                start_date=datetime(2024, 1, 1).date(),
                end_date=datetime(2024, 6, 1).date(),
            )

    def test_backtest_error_from_the_underlying_service_becomes_a_structured_output(
        self, db_session
    ):
        user = _make_user(db_session)
        _seed_security(db_session, ticker="AAPL", name="Apple Inc.")
        _ingest_prices(db_session, ["AAPL"])

        result = TOOLS_BY_NAME["run_backtest"].handler(
            db_session,
            user,
            BacktestInput(
                tickers=["AAPL"],
                start_date=datetime(1999, 1, 1).date(),
                end_date=datetime(1999, 6, 1).date(),
            ),
        )

        assert "error" in result.output
        assert result.evidence == []


class TestGetFundamentals:
    def test_unknown_ticker(self, db_session):
        user = _make_user(db_session)
        result = TOOLS_BY_NAME["get_fundamentals"].handler(
            db_session, user, TickerInput(ticker="NOPE")
        )
        assert "error" in result.output
        assert result.evidence == []

    def test_no_fundamentals_ingested_reports_unavailable_no_evidence(self, db_session):
        user = _make_user(db_session)
        _seed_security(db_session)
        result = TOOLS_BY_NAME["get_fundamentals"].handler(
            db_session, user, TickerInput(ticker="AAPL")
        )
        assert result.output["available"] is False
        assert result.evidence == []  # no fabricated evidence for unavailable data

    def test_ingested_facts_produce_fundamentals_evidence(self, db_session):
        from datetime import date
        from decimal import Decimal

        from app.providers.base import CompanyFactsResult, FundamentalFact
        from app.repositories.fundamentals_repository import FundamentalsRepository

        user = _make_user(db_session)
        security = _seed_security(db_session)
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

        result = TOOLS_BY_NAME["get_fundamentals"].handler(
            db_session, user, TickerInput(ticker="AAPL")
        )
        assert result.output["available"] is True
        [evidence] = result.evidence
        assert evidence.source_type == EvidenceSourceType.FUNDAMENTALS
        assert evidence.provenance == "SECEdgarFundamentalsProvider"


class TestGetMacroIndicators:
    def test_untracked_series_reports_unavailable_no_evidence(self, db_session):
        from app.agent.tools import MacroSeriesInput

        user = _make_user(db_session)
        result = TOOLS_BY_NAME["get_macro_indicators"].handler(
            db_session, user, MacroSeriesInput(series_id="NOT_A_REAL_SERIES")
        )
        assert result.output["available"] is False
        assert result.evidence == []

    def test_ingested_observations_produce_macro_evidence(self, db_session):
        from decimal import Decimal

        from app.agent.tools import MacroSeriesInput
        from app.providers.base import MacroObservationData
        from app.repositories.macro_repository import MacroRepository

        user = _make_user(db_session)
        MacroRepository(db_session).upsert_observations(
            series_id="FEDFUNDS",
            observations=[
                MacroObservationData(
                    series_id="FEDFUNDS", observation_date=datetime(2024, 1, 1).date(),
                    value=Decimal("5.33"), unit="Percent", frequency="Monthly",
                    vintage_date=datetime(2024, 2, 1).date(),
                )
            ],
            source="FREDMacroProvider",
            retrieved_at=datetime.now(UTC),
        )
        db_session.flush()

        result = TOOLS_BY_NAME["get_macro_indicators"].handler(
            db_session, user, MacroSeriesInput(series_id="fedfunds")
        )
        assert result.output["available"] is True
        [evidence] = result.evidence
        assert evidence.source_type == EvidenceSourceType.MACRO
        assert evidence.ticker is None


class TestGetDataSourceStatus:
    def test_returns_all_provider_categories_with_evidence(self, db_session):
        from app.agent.tools import EmptyInput

        user = _make_user(db_session)
        result = TOOLS_BY_NAME["get_data_source_status"].handler(db_session, user, EmptyInput())

        categories = {p["category"] for p in result.output["providers"]}
        assert categories == {"market_data", "news", "fundamentals", "macro"}
        [evidence] = result.evidence
        assert evidence.source_type == EvidenceSourceType.SYSTEM
        # Never a credential value anywhere in the tool's output.
        for provider in result.output["providers"]:
            assert set(provider.keys()) >= {"credential_required", "credential_configured"}
            assert "api_key" not in provider
