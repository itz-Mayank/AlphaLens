"""Unit tests for TwelveDataMarketDataProvider — all HTTP mocked, no real
network access and no real API key. Live validation was not performed (no
Twelve Data key available in this session; also unnecessary for a free
tier explicitly barred from commercial use — see docs/decisions.md's
Phase 10 provider-ecosystem ADR).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.providers.base import OHLCVBar
from app.providers.http_client import ProviderRateLimitedError, ProviderResponseError
from app.providers.market_data.twelvedata import TwelveDataMarketDataProvider


class _FakeResponse:
    def __init__(self, status_code: int, json_body=None):
        self.status_code = status_code
        self._json_body = json_body
        self.text = ""
        self.headers: dict = {}

    def json(self):
        return self._json_body


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.requests: list[dict] = []

    def request(self, method, url, *, params=None, headers=None, timeout=None):
        self.requests.append(params or {})
        return self._response


class TestConstructorValidation:
    def test_rejects_an_empty_api_key(self):
        with pytest.raises(ValueError, match="API key"):
            TwelveDataMarketDataProvider(api_key="")


class TestListSecuritiesNotImplemented:
    def test_never_enumerates_a_full_vendor_universe(self):
        provider = TwelveDataMarketDataProvider(
            api_key="fake-key", client=_FakeClient(_FakeResponse(200))
        )
        with pytest.raises(NotImplementedError):
            provider.list_securities()


class TestSuccessfulFetch:
    def test_parses_and_sorts_bars_ascending(self):
        body = {
            "values": [
                {
                    "datetime": "2024-01-02",
                    "open": "185.0",
                    "high": "186.0",
                    "low": "184.0",
                    "close": "185.5",
                    "volume": "1000",
                },
                {
                    "datetime": "2024-01-01",
                    "open": "184.0",
                    "high": "185.0",
                    "low": "183.0",
                    "close": "184.5",
                    "volume": "900",
                },
            ]
        }
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)

        bars = provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))

        assert [b.ts for b in bars] == [date(2024, 1, 1), date(2024, 1, 2)]
        assert all(isinstance(b, OHLCVBar) for b in bars)
        assert bars[0].close == Decimal("184.5")
        assert bars[0].adjusted_close == bars[0].close

    def test_sends_interval_and_date_range_params(self):
        client = _FakeClient(_FakeResponse(200, json_body={"values": []}))
        provider = TwelveDataMarketDataProvider(api_key="secret-key", client=client)
        provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 31))

        params = client.requests[0]
        assert params["symbol"] == "AAPL"
        assert params["interval"] == "1day"
        assert params["apikey"] == "secret-key"
        assert params["start_date"] == "2024-01-01"
        assert params["end_date"] == "2024-01-31"


class TestErrorBodyConventions:
    """Twelve Data returns HTTP 200 with a `{"status": "error", ...}` body
    rather than a 4xx/5xx status code for these cases."""

    def test_rate_limit_error_code_raises_provider_rate_limited(self):
        body = {"status": "error", "code": 429, "message": "You have run out of API credits"}
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)
        with pytest.raises(ProviderRateLimitedError):
            provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))

    def test_auth_error_code_raises_provider_response_error(self):
        body = {"status": "error", "code": 401, "message": "Invalid API key"}
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = TwelveDataMarketDataProvider(api_key="bad-key", client=client)
        with pytest.raises(ProviderResponseError):
            provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))

    def test_unknown_ticker_error_code_returns_empty_list_not_an_exception(self):
        body = {"status": "error", "code": 400, "message": "**symbol** not found"}
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)
        assert provider.get_daily_bars("NOTREAL", date(2024, 1, 1), date(2024, 1, 2)) == []


class TestSearchSecurities:
    def test_parses_matches_and_filters_to_equity_instrument_types(self):
        body = {
            "data": [
                {
                    "symbol": "AMD",
                    "instrument_name": "Advanced Micro Devices Inc",
                    "exchange": "NASDAQ",
                    "instrument_type": "Common Stock",
                    "country": "United States",
                    "currency": "USD",
                },
                {
                    "symbol": "AMDUSD",
                    "instrument_name": "AMD / US Dollar",
                    "exchange": "Forex",
                    "instrument_type": "Physical Currency",
                    "country": "",
                    "currency": "USD",
                },
            ],
            "status": "ok",
        }
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)

        results = provider.search_securities("AMD")

        assert len(results) == 1
        assert results[0].ticker == "AMD"
        assert results[0].name == "Advanced Micro Devices Inc"
        assert results[0].exchange == "NASDAQ"

    def test_deduplicates_the_same_ticker_across_multiple_exchanges(self):
        body = {
            "data": [
                {
                    "symbol": "AAPL",
                    "instrument_name": "Apple Inc",
                    "exchange": "NASDAQ",
                    "instrument_type": "Common Stock",
                    "currency": "USD",
                },
                {
                    "symbol": "AAPL",
                    "instrument_name": "Apple Inc",
                    "exchange": "SWX",
                    "instrument_type": "Common Stock",
                    "currency": "CHF",
                },
            ],
            "status": "ok",
        }
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)

        results = provider.search_securities("AAPL")

        assert len(results) == 1
        assert results[0].exchange == "NASDAQ"

    def test_empty_query_returns_no_results_without_a_request(self):
        client = _FakeClient(_FakeResponse(200, json_body={"data": []}))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)

        assert provider.search_securities("   ") == []
        assert client.requests == []

    def test_rate_limit_error_code_raises_provider_rate_limited(self):
        body = {"status": "error", "code": 429, "message": "You have run out of API credits"}
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)
        with pytest.raises(ProviderRateLimitedError):
            provider.search_securities("AMD")

    def test_malformed_response_raises_provider_response_error(self):
        client = _FakeClient(_FakeResponse(200, json_body={"unexpected": True}))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)
        with pytest.raises(ProviderResponseError):
            provider.search_securities("AMD")


class TestMalformedResponses:
    def test_response_missing_values_key_raises_provider_response_error(self):
        client = _FakeClient(_FakeResponse(200, json_body={"meta": {}}))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)
        with pytest.raises(ProviderResponseError):
            provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))

    def test_a_malformed_individual_bar_is_skipped_not_fatal(self):
        body = {
            "values": [
                {
                    "datetime": "2024-01-01", "open": "not-a-number",
                    "high": "1", "low": "1", "close": "1",
                },
                {
                    "datetime": "2024-01-02",
                    "open": "185.0",
                    "high": "186.0",
                    "low": "184.0",
                    "close": "185.5",
                    "volume": "1000",
                },
            ]
        }
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = TwelveDataMarketDataProvider(api_key="fake-key", client=client)
        bars = provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))
        assert len(bars) == 1
        assert bars[0].ts == date(2024, 1, 2)
