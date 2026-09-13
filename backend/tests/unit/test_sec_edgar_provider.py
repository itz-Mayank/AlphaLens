"""Unit tests for SECEdgarFundamentalsProvider — all HTTP mocked via an
injected fake `httpx.Client`-shaped object, no real network access. A real,
credential-free live check against data.sec.gov exists separately as
`tests/integration/test_sec_edgar_live.py` (`@pytest.mark.live_provider`).
"""

from __future__ import annotations

import pytest
from app.providers.base import CompanyFactsResult
from app.providers.fundamentals.sec_edgar import SECEdgarFundamentalsProvider
from app.providers.http_client import ProviderResponseError


class _FakeResponse:
    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text
        self.headers: dict = {}

    def json(self):
        return self._json_body


class _FakeClient:
    """Keyed by URL substring so a test can serve different bodies for the
    ticker-map endpoint vs. the company-facts endpoint."""

    def __init__(self, by_url: dict[str, _FakeResponse]):
        self._by_url = by_url
        self.requests: list[tuple[str, dict | None]] = []

    def request(self, method, url, *, params=None, headers=None, timeout=None):
        self.requests.append((url, headers))
        for key, response in self._by_url.items():
            if key in url:
                return response
        raise AssertionError(f"No fake response registered for {url}")


_TICKER_MAP = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}

_COMPANY_FACTS = {
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Assets": {
                "units": {
                    "USD": [
                        {
                            "end": "2023-09-30",
                            "val": 352755000000,
                            "accn": "0000320193-23-000106",
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2023-11-03",
                        },
                        # Malformed: missing "val" — must be skipped, not fatal.
                        {
                            "end": "2022-09-24",
                            "accn": "0000320193-22-000108",
                            "form": "10-K",
                            "filed": "2022-10-28",
                        },
                    ]
                }
            },
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "start": "2022-10-01",
                            "end": "2023-09-30",
                            "val": 383285000000,
                            "accn": "0000320193-23-000106",
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2023-11-03",
                        }
                    ]
                }
            },
        }
    },
}


def _provider(client: _FakeClient) -> SECEdgarFundamentalsProvider:
    return SECEdgarFundamentalsProvider(user_agent="AlphaLens test test@example.com", client=client)


class TestConstructorValidation:
    def test_rejects_a_user_agent_without_a_contact_address(self):
        with pytest.raises(ValueError, match="User-Agent"):
            SECEdgarFundamentalsProvider(user_agent="AlphaLens", client=_FakeClient({}))

    def test_rejects_an_empty_user_agent(self):
        with pytest.raises(ValueError):
            SECEdgarFundamentalsProvider(user_agent="", client=_FakeClient({}))


class TestUnknownTicker:
    def test_returns_none_for_a_ticker_not_in_the_sec_map(self):
        client = _FakeClient({"company_tickers.json": _FakeResponse(200, json_body=_TICKER_MAP)})
        provider = _provider(client)
        assert provider.get_company_facts("NOPE") is None


class TestSuccessfulFetch:
    def test_parses_supported_concepts_and_skips_malformed_entries(self):
        client = _FakeClient(
            {
                "company_tickers.json": _FakeResponse(200, json_body=_TICKER_MAP),
                "companyfacts": _FakeResponse(200, json_body=_COMPANY_FACTS),
            }
        )
        provider = _provider(client)
        result = provider.get_company_facts("aapl")

        assert isinstance(result, CompanyFactsResult)
        assert result.ticker == "AAPL"
        assert result.external_id == "CIK0000320193"
        assert result.company_name == "Apple Inc."

        concepts = {fact.concept for fact in result.facts}
        assert concepts == {"Assets", "Revenues"}
        assert len(result.facts) == 2  # the malformed Assets entry was skipped

        revenue = next(f for f in result.facts if f.concept == "Revenues")
        assert revenue.period_start.isoformat() == "2022-10-01"
        assert revenue.period_end.isoformat() == "2023-09-30"
        assert revenue.fiscal_year == 2023
        assert revenue.form == "10-K"
        assert revenue.accession_number == "0000320193-23-000106"

    def test_sends_an_identifying_user_agent_on_every_request(self):
        client = _FakeClient(
            {
                "company_tickers.json": _FakeResponse(200, json_body=_TICKER_MAP),
                "companyfacts": _FakeResponse(200, json_body=_COMPANY_FACTS),
            }
        )
        provider = _provider(client)
        provider.get_company_facts("AAPL")
        assert all(
            headers is not None and "@" in headers["User-Agent"] for _, headers in client.requests
        )

    def test_ticker_map_is_cached_across_calls(self):
        client = _FakeClient(
            {
                "company_tickers.json": _FakeResponse(200, json_body=_TICKER_MAP),
                "companyfacts": _FakeResponse(200, json_body=_COMPANY_FACTS),
            }
        )
        provider = _provider(client)
        provider.get_company_facts("AAPL")
        provider.get_company_facts("AAPL")
        ticker_map_requests = [u for u, _ in client.requests if "company_tickers.json" in u]
        assert len(ticker_map_requests) == 1


class TestMalformedResponses:
    def test_malformed_ticker_map_entry_raises_provider_response_error(self):
        client = _FakeClient(
            {"company_tickers.json": _FakeResponse(200, json_body={"0": {"ticker": "AAPL"}})}
        )
        provider = _provider(client)
        with pytest.raises(ProviderResponseError):
            provider.get_company_facts("AAPL")

    def test_company_facts_response_missing_facts_key_raises(self):
        client = _FakeClient(
            {
                "company_tickers.json": _FakeResponse(200, json_body=_TICKER_MAP),
                "companyfacts": _FakeResponse(200, json_body={"entityName": "Apple Inc."}),
            }
        )
        provider = _provider(client)
        with pytest.raises(ProviderResponseError):
            provider.get_company_facts("AAPL")
