from datetime import UTC, datetime

from app.providers.base import NewsArticleData
from app.services.news_processing import (
    deduplicate_articles,
    filter_supported_language,
    is_duplicate_content,
    normalize_article,
    normalize_text,
    sentiment_input_text,
)


def _article(**overrides) -> NewsArticleData:
    defaults = dict(
        external_id="AAPL-0",
        title="Company reports record profits",
        summary="The company beat expectations.",
        url="https://demo-news.invalid/aapl/0",
        publisher="Demo Wire",
        published_at=datetime(2026, 9, 10, tzinfo=UTC),
        language="en",
    )
    defaults.update(overrides)
    return NewsArticleData(**defaults)


class TestNormalizeText:
    def test_collapses_multiple_whitespace_to_single_space(self):
        assert (
            normalize_text("Company   reports\n\nrecord   profits")
            == "Company reports record profits"
        )

    def test_strips_leading_and_trailing_whitespace(self):
        assert normalize_text("  Company reports profits  \n") == "Company reports profits"

    def test_preserves_financial_terminology(self):
        text = "Revenue up +15% to $2.3B in Q3, EPS of $1.42"
        assert normalize_text(text) == text

    def test_preserves_casing(self):
        assert normalize_text("AAPL shares Rise") == "AAPL shares Rise"


class TestNormalizeArticle:
    def test_normalizes_title_and_summary_only(self):
        article = _article(title="Company  reports\nprofits", summary="Beat   expectations.")
        normalized = normalize_article(article)
        assert normalized.title == "Company reports profits"
        assert normalized.summary == "Beat expectations."
        assert normalized.url == article.url
        assert normalized.external_id == article.external_id

    def test_none_summary_stays_none(self):
        article = _article(summary=None)
        assert normalize_article(article).summary is None


class TestSentimentInputText:
    def test_combines_title_and_summary(self):
        article = _article(title="Headline", summary="A summary sentence.")
        assert sentiment_input_text(article) == "Headline. A summary sentence."

    def test_falls_back_to_title_only_when_no_summary(self):
        article = _article(title="Headline only", summary=None)
        assert sentiment_input_text(article) == "Headline only"


class TestDuplicateDetection:
    def test_identical_title_and_summary_is_duplicate(self):
        a = _article(external_id="A-1")
        b = _article(external_id="A-2")
        assert is_duplicate_content(a, b) is True

    def test_different_title_is_not_duplicate(self):
        a = _article(title="Company reports record profits")
        b = _article(title="Company shares fall on weak guidance")
        assert is_duplicate_content(a, b) is False

    def test_different_summary_is_not_duplicate(self):
        a = _article(summary="Beat expectations by a wide margin.")
        b = _article(summary="Slightly missed expectations.")
        assert is_duplicate_content(a, b) is False

    def test_whitespace_differences_are_still_duplicate(self):
        a = _article(title="Company  reports profits")
        b = _article(title="Company reports  profits")
        assert is_duplicate_content(a, b) is True


class TestDeduplicateArticles:
    def test_keeps_the_first_occurrence_of_duplicate_content(self):
        first = _article(external_id="A-1")
        duplicate = _article(external_id="A-2")
        distinct = _article(external_id="A-3", title="A completely different headline")

        result = deduplicate_articles([first, duplicate, distinct])

        assert [a.external_id for a in result] == ["A-1", "A-3"]

    def test_no_duplicates_returns_all_articles(self):
        articles = [
            _article(external_id="A-1", title="Headline one"),
            _article(external_id="A-2", title="Headline two"),
        ]
        assert deduplicate_articles(articles) == articles

    def test_empty_list_returns_empty_list(self):
        assert deduplicate_articles([]) == []


class TestFilterSupportedLanguage:
    def test_splits_by_language(self):
        english = _article(external_id="A-1", language="en")
        spanish = _article(external_id="A-2", language="es")

        supported, filtered_out = filter_supported_language([english, spanish])

        assert supported == [english]
        assert filtered_out == [spanish]

    def test_all_english_none_filtered(self):
        articles = [_article(external_id="A-1"), _article(external_id="A-2")]
        supported, filtered_out = filter_supported_language(articles)
        assert supported == articles
        assert filtered_out == []
