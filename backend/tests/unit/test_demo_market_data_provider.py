from datetime import date

from app.providers.market_data.demo import DemoMarketDataProvider


def test_list_securities_returns_a_fixed_non_empty_universe():
    provider = DemoMarketDataProvider()

    securities = provider.list_securities()

    assert len(securities) >= 10
    tickers = {s.ticker for s in securities}
    assert "AAPL" in tickers
    assert all(s.currency == "USD" for s in securities)


def test_get_daily_bars_returns_only_business_days():
    provider = DemoMarketDataProvider()

    bars = provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 14))

    assert all(bar.ts.weekday() < 5 for bar in bars)
    assert len(bars) == 10  # 2024-01-01..01-14 has 10 weekdays


def test_get_daily_bars_every_bar_is_internally_consistent():
    provider = DemoMarketDataProvider()

    bars = provider.get_daily_bars("MSFT", date(2023, 1, 1), date(2023, 6, 30))

    assert len(bars) > 100
    for bar in bars:
        assert bar.low <= bar.open <= bar.high
        assert bar.low <= bar.close <= bar.high
        assert bar.open > 0 and bar.volume >= 0


def test_get_daily_bars_is_deterministic_across_repeated_calls():
    provider = DemoMarketDataProvider()

    first = provider.get_daily_bars("NVDA", date(2023, 1, 1), date(2023, 12, 31))
    second = provider.get_daily_bars("NVDA", date(2023, 1, 1), date(2023, 12, 31))

    assert first == second


def test_get_daily_bars_is_stable_regardless_of_requested_start():
    """The idempotency guarantee this backs: ingesting a wider window later
    must reproduce, byte-for-byte, whatever a narrower window already
    ingested — otherwise re-ingestion would look like an "update" every
    time instead of proving nothing changed."""
    provider = DemoMarketDataProvider()

    full_year = provider.get_daily_bars("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    second_half = provider.get_daily_bars("AAPL", date(2023, 7, 1), date(2023, 12, 31))

    overlap = [bar for bar in full_year if bar.ts >= date(2023, 7, 1)]
    assert overlap == second_half


def test_get_daily_bars_returns_empty_for_unknown_ticker():
    provider = DemoMarketDataProvider()

    assert provider.get_daily_bars("NOTATICKER", date(2023, 1, 1), date(2023, 12, 31)) == []


def test_get_daily_bars_returns_empty_when_end_before_genesis():
    provider = DemoMarketDataProvider()

    assert provider.get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 12, 31)) == []


def test_search_securities_matches_by_ticker():
    provider = DemoMarketDataProvider()

    results = provider.search_securities("AAPL")

    assert [s.ticker for s in results] == ["AAPL"]


def test_search_securities_matches_by_company_name_case_insensitively():
    provider = DemoMarketDataProvider()

    results = provider.search_securities("microsoft")

    assert [s.ticker for s in results] == ["MSFT"]


def test_search_securities_respects_limit():
    provider = DemoMarketDataProvider()

    results = provider.search_securities("A", limit=2)

    assert len(results) == 2


def test_search_securities_returns_empty_for_no_match():
    provider = DemoMarketDataProvider()

    assert provider.search_securities("ZZZNOTREAL") == []


def test_search_securities_returns_empty_for_a_blank_query():
    provider = DemoMarketDataProvider()

    assert provider.search_securities("   ") == []
