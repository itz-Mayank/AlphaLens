"""Unit tests for FREDMacroProvider — all HTTP mocked, no real network
access and no real API key. Live validation was not performed (no FRED key
available in this session — see docs/decisions.md's Phase 10
provider-ecosystem ADR); this is exactly why the adapter boundary must be
solidly covered by mocked tests instead.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.providers.base import MacroObservationData
from app.providers.http_client import ProviderResponseError
from app.providers.macro.fred import FREDMacroProvider


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
            FREDMacroProvider(api_key="")


class TestSuccessfulFetch:
    def test_parses_observations_with_known_series_metadata(self):
        body = {
            "observations": [
                {"date": "2024-01-01", "value": "5.33", "realtime_start": "2024-02-01"},
                {"date": "2024-02-01", "value": "5.33", "realtime_start": "2024-03-01"},
            ]
        }
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = FREDMacroProvider(api_key="fake-key", client=client)

        result = provider.get_observations(
            "FEDFUNDS", start=date(2024, 1, 1), end=date(2024, 2, 28)
        )

        assert len(result) == 2
        assert all(isinstance(o, MacroObservationData) for o in result)
        assert result[0].value == Decimal("5.33")
        assert result[0].unit == "Percent"
        assert result[0].frequency == "Monthly"
        assert result[0].vintage_date == date(2024, 2, 1)

    def test_sends_the_api_key_and_date_range_as_params(self):
        client = _FakeClient(_FakeResponse(200, json_body={"observations": []}))
        provider = FREDMacroProvider(api_key="secret-123", client=client)
        provider.get_observations("CPIAUCSL", start=date(2024, 1, 1), end=date(2024, 3, 1))

        assert client.requests[0]["api_key"] == "secret-123"
        assert client.requests[0]["series_id"] == "CPIAUCSL"
        assert client.requests[0]["observation_start"] == "2024-01-01"
        assert client.requests[0]["observation_end"] == "2024-03-01"

    def test_unknown_series_id_gets_unknown_unit_and_frequency(self):
        body = {"observations": [{"date": "2024-01-01", "value": "1.0"}]}
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = FREDMacroProvider(api_key="fake-key", client=client)
        result = provider.get_observations(
            "SOME_OTHER_SERIES", start=date(2024, 1, 1), end=date(2024, 1, 2)
        )
        assert result[0].unit == "Unknown"
        assert result[0].frequency == "Unknown"


class TestMissingValueNeverBecomesZero:
    def test_a_dot_value_is_none_not_zero(self):
        body = {"observations": [{"date": "2024-01-01", "value": "."}]}
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = FREDMacroProvider(api_key="fake-key", client=client)
        result = provider.get_observations("GDP", start=date(2024, 1, 1), end=date(2024, 1, 2))
        assert len(result) == 1
        assert result[0].value is None


class TestMalformedData:
    def test_a_row_with_an_unparseable_date_is_skipped_not_fatal(self):
        body = {
            "observations": [
                {"date": "not-a-date", "value": "1.0"},
                {"date": "2024-01-01", "value": "2.0"},
            ]
        }
        client = _FakeClient(_FakeResponse(200, json_body=body))
        provider = FREDMacroProvider(api_key="fake-key", client=client)
        result = provider.get_observations("GDP", start=date(2024, 1, 1), end=date(2024, 1, 2))
        assert len(result) == 1
        assert result[0].observation_date == date(2024, 1, 1)

    def test_a_response_missing_observations_key_raises_provider_response_error(self):
        client = _FakeClient(_FakeResponse(200, json_body={"error_message": "bad request"}))
        provider = FREDMacroProvider(api_key="fake-key", client=client)
        with pytest.raises(ProviderResponseError):
            provider.get_observations("GDP", start=date(2024, 1, 1), end=date(2024, 1, 2))
