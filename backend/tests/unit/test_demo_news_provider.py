from datetime import UTC, datetime, timedelta

from app.providers.news.demo import DemoNewsProvider

SINCE = datetime(2026, 9, 1, tzinfo=UTC)
UNTIL = datetime(2026, 9, 8, tzinfo=UTC)


class TestDemoNewsProvider:
    def test_returns_articles_for_the_full_universe_when_no_tickers_given(self):
        provider = DemoNewsProvider()
        articles = provider.fetch_articles(tickers=None, since=SINCE, until=UNTIL, limit=1000)
        assert len(articles) > 0
        assert any(a.external_id.startswith("AAPL-") for a in articles)
        assert any(a.external_id.startswith("JPM-") for a in articles)

    def test_filters_to_requested_tickers_only(self):
        provider = DemoNewsProvider()
        articles = provider.fetch_articles(tickers=["AAPL"], since=SINCE, until=UNTIL, limit=1000)
        assert len(articles) > 0
        assert all(a.external_id.startswith("AAPL-") for a in articles)

    def test_unknown_ticker_returns_no_articles(self):
        provider = DemoNewsProvider()
        articles = provider.fetch_articles(tickers=["ZZZZ"], since=SINCE, until=UNTIL, limit=1000)
        assert articles == []

    def test_respects_the_limit(self):
        provider = DemoNewsProvider()
        articles = provider.fetch_articles(tickers=None, since=SINCE, until=UNTIL, limit=3)
        assert len(articles) == 3

    def test_articles_are_newest_first(self):
        provider = DemoNewsProvider()
        articles = provider.fetch_articles(tickers=["AAPL"], since=SINCE, until=UNTIL, limit=1000)
        published_dates = [a.published_at for a in articles]
        assert published_dates == sorted(published_dates, reverse=True)

    def test_all_articles_fall_within_the_requested_window(self):
        provider = DemoNewsProvider()
        articles = provider.fetch_articles(tickers=None, since=SINCE, until=UNTIL, limit=1000)
        assert all(SINCE <= a.published_at <= UNTIL for a in articles)

    def test_is_deterministic_for_the_same_window(self):
        """Pure function of its inputs — mirrors DemoMarketDataProvider's
        determinism contract, not wall-clock time."""
        provider = DemoNewsProvider()
        first = provider.fetch_articles(tickers=["AAPL"], since=SINCE, until=UNTIL, limit=1000)
        second = provider.fetch_articles(tickers=["AAPL"], since=SINCE, until=UNTIL, limit=1000)
        assert first == second

    def test_different_windows_can_shift_article_timing(self):
        provider = DemoNewsProvider()
        first = provider.fetch_articles(tickers=["AAPL"], since=SINCE, until=UNTIL, limit=1000)
        shifted_until = UNTIL + timedelta(days=10)
        second = provider.fetch_articles(
            tickers=["AAPL"], since=SINCE, until=shifted_until, limit=1000
        )
        first_by_id = {a.external_id: a.published_at for a in first}
        second_by_id = {a.external_id: a.published_at for a in second}
        assert first_by_id != second_by_id

    def test_invalid_window_returns_no_articles(self):
        provider = DemoNewsProvider()
        articles = provider.fetch_articles(tickers=None, since=UNTIL, until=SINCE, limit=1000)
        assert articles == []

    def test_urls_use_the_invalid_tld_never_a_real_domain(self):
        provider = DemoNewsProvider()
        articles = provider.fetch_articles(tickers=["AAPL"], since=SINCE, until=UNTIL, limit=1000)
        assert all(".invalid/" in a.url for a in articles)

    def test_articles_are_labeled_as_english(self):
        provider = DemoNewsProvider()
        articles = provider.fetch_articles(tickers=["AAPL"], since=SINCE, until=UNTIL, limit=1000)
        assert all(a.language == "en" for a in articles)
