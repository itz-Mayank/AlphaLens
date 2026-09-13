from datetime import UTC, datetime

from app.agent.evidence import Evidence, EvidenceSourceType


def _evidence(**overrides) -> Evidence:
    defaults = dict(
        source_type=EvidenceSourceType.FORECAST,
        source_id="forecast:AAPL",
        ticker="AAPL",
        timestamp=datetime(2026, 9, 11, tzinfo=UTC),
        data={"expected_return": 0.0045},
        provenance="xgboost_return-v1",
    )
    defaults.update(overrides)
    return Evidence(**defaults)


class TestEvidenceAsDict:
    def test_serializes_every_field(self):
        evidence = _evidence()
        result = evidence.as_dict()
        assert result == {
            "source_type": "FORECAST",
            "source_id": "forecast:AAPL",
            "ticker": "AAPL",
            "timestamp": "2026-09-11T00:00:00+00:00",
            "data": {"expected_return": 0.0045},
            "provenance": "xgboost_return-v1",
        }

    def test_ticker_none_is_preserved_for_ticker_agnostic_evidence(self):
        evidence = _evidence(source_type=EvidenceSourceType.BACKTEST, ticker=None)
        assert evidence.as_dict()["ticker"] is None


class TestCitationTag:
    def test_forecast_tag(self):
        assert _evidence(source_type=EvidenceSourceType.FORECAST).citation_tag() == "[Forecast]"

    def test_shap_tag_is_all_caps_not_titlecased(self):
        """`.title()` on "SHAP" would incorrectly produce "Shap" — this
        proves the display-name mapping is actually used, not a naive
        `.title()` fallback."""
        assert _evidence(source_type=EvidenceSourceType.SHAP).citation_tag() == "[SHAP]"

    def test_market_data_tag_has_a_space(self):
        assert (
            _evidence(source_type=EvidenceSourceType.MARKET_DATA).citation_tag()
            == "[Market Data]"
        )

    def test_news_tag(self):
        assert _evidence(source_type=EvidenceSourceType.NEWS).citation_tag() == "[News]"

    def test_sentiment_tag(self):
        assert _evidence(source_type=EvidenceSourceType.SENTIMENT).citation_tag() == "[Sentiment]"

    def test_backtest_tag(self):
        assert _evidence(source_type=EvidenceSourceType.BACKTEST).citation_tag() == "[Backtest]"

    def test_every_source_type_has_a_tag(self):
        for source_type in EvidenceSourceType.ALL:
            tag = _evidence(source_type=source_type).citation_tag()
            assert tag.startswith("[") and tag.endswith("]")
