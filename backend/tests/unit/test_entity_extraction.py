from decimal import Decimal

from app.db.models.news import EntityMatchMethod
from app.db.models.security import Security
from app.services.entity_extraction_service import MIN_CONFIDENCE, extract_entities


def _security(id_: int, ticker: str, name: str) -> Security:
    security = Security(ticker=ticker, name=name, exchange="NASDAQ", currency="USD")
    security.id = id_
    return security


AAPL = _security(1, "AAPL", "Apple Inc.")
MSFT = _security(2, "MSFT", "Microsoft Corporation")
JPM = _security(3, "JPM", "JPMorgan Chase & Co.")
AMZN = _security(4, "AMZN", "Amazon.com, Inc.")
UNIVERSE = [AAPL, MSFT, JPM, AMZN]


class TestTickerSymbolMatching:
    def test_cashtag_mention_matches(self):
        matches = extract_entities("Investors are watching $AAPL closely this week.", UNIVERSE)
        assert len(matches) == 1
        assert matches[0].security_id == AAPL.id
        assert matches[0].match_method == EntityMatchMethod.TICKER_SYMBOL

    def test_parenthetical_ticker_matches(self):
        matches = extract_entities("Apple Inc. (AAPL) reported record profits.", UNIVERSE)
        assert any(
            m.security_id == AAPL.id and m.match_method == EntityMatchMethod.TICKER_SYMBOL
            for m in matches
        )

    def test_ticker_match_has_high_confidence(self):
        matches = extract_entities("$MSFT shares rose today.", UNIVERSE)
        assert matches[0].confidence >= Decimal("0.9")


class TestCompanyNameMatching:
    def test_known_company_matches_by_name(self):
        matches = extract_entities("Microsoft reported strong cloud revenue growth.", UNIVERSE)
        assert len(matches) == 1
        assert matches[0].security_id == MSFT.id
        assert matches[0].match_method == EntityMatchMethod.COMPANY_NAME

    def test_multi_word_company_name_matches(self):
        matches = extract_entities("JPMorgan Chase posted higher trading revenue.", UNIVERSE)
        assert any(m.security_id == JPM.id for m in matches)

    def test_name_with_internal_punctuation_matches(self):
        matches = extract_entities("Amazon.com announced a new logistics hub.", UNIVERSE)
        assert any(m.security_id == AMZN.id for m in matches)

    def test_unknown_company_produces_no_match(self):
        matches = extract_entities("A small local bakery announced record sales.", UNIVERSE)
        assert matches == []

    def test_no_entity_in_generic_text_produces_no_match(self):
        matches = extract_entities(
            "The weather was sunny across most of the region today.", UNIVERSE
        )
        assert matches == []


class TestAmbiguityHandling:
    def test_ordinary_lowercase_word_does_not_false_positive(self):
        """ "Apple" (the company's core name after stripping "Inc.") is also
        an ordinary English word — lowercase usage as the fruit must not
        be mistaken for the company."""
        matches = extract_entities("I ate an apple and an orange for breakfast.", UNIVERSE)
        assert matches == []

    def test_properly_capitalized_company_name_does_match(self):
        """The same core name, capitalized as a real headline would write
        the company, must match."""
        matches = extract_entities("Apple reported strong iPhone sales this quarter.", UNIVERSE)
        assert any(m.security_id == AAPL.id for m in matches)

    def test_multiple_companies_in_one_article_are_all_matched(self):
        matches = extract_entities(
            "Both Apple and Microsoft reported earnings that beat expectations.", UNIVERSE
        )
        matched_ids = {m.security_id for m in matches}
        assert matched_ids == {AAPL.id, MSFT.id}

    def test_no_match_ever_falls_below_the_minimum_confidence(self):
        matches = extract_entities("Apple Microsoft JPMorgan Chase Amazon.com", UNIVERSE)
        assert all(m.confidence >= MIN_CONFIDENCE for m in matches)

    def test_empty_text_produces_no_match(self):
        assert extract_entities("", UNIVERSE) == []

    def test_empty_universe_produces_no_match(self):
        assert extract_entities("Apple reported earnings.", []) == []
