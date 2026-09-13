"""Tests for `app/providers/http_client.py`'s bounded retry/backoff policy
— every real provider adapter (SEC EDGAR, Twelve Data, FRED) depends on
this. All HTTP is mocked (`httpx.Client` monkeypatched); `sleep` is a
recording stub so retry/backoff behavior is asserted without a real delay.
"""

from __future__ import annotations

import httpx
import pytest
from app.providers.http_client import (
    ProviderRateLimitedError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    request_json,
)


class _FakeResponse:
    def __init__(self, status_code: int, *, json_body=None, text: str = "", headers=None):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json_body is _MALFORMED:
            raise ValueError("not json")
        return self._json_body


_MALFORMED = object()


class _RecordingSleep:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def request(self, method, url, *, params=None, headers=None, timeout=None):
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TestSuccessfulRequest:
    def test_returns_parsed_json_on_a_clean_200(self):
        client = _FakeClient([_FakeResponse(200, json_body={"ok": True})])
        result = request_json(client, "GET", "https://example.test/api")
        assert result == {"ok": True}
        assert client.calls == 1


class TestTimeoutRetry:
    def test_retries_up_to_max_then_raises(self):
        sleep = _RecordingSleep()
        client = _FakeClient(
            [
                httpx.TimeoutException("slow"),
                httpx.TimeoutException("slow"),
                httpx.TimeoutException("slow"),
                httpx.TimeoutException("slow"),
            ]
        )
        with pytest.raises(ProviderTimeoutError):
            request_json(client, "GET", "https://example.test/api", max_retries=3, sleep=sleep)
        assert client.calls == 4  # original + 3 retries
        assert len(sleep.calls) == 3

    def test_succeeds_after_a_transient_timeout(self):
        sleep = _RecordingSleep()
        client = _FakeClient(
            [httpx.TimeoutException("slow"), _FakeResponse(200, json_body={"a": 1})]
        )
        result = request_json(client, "GET", "https://example.test/api", sleep=sleep)
        assert result == {"a": 1}
        assert len(sleep.calls) == 1


class TestRateLimitHandling:
    def test_respects_retry_after_header(self):
        sleep = _RecordingSleep()
        client = _FakeClient(
            [
                _FakeResponse(429, headers={"Retry-After": "7"}),
                _FakeResponse(200, json_body={"ok": True}),
            ]
        )
        result = request_json(client, "GET", "https://example.test/api", sleep=sleep)
        assert result == {"ok": True}
        assert sleep.calls == [7.0]

    def test_raises_provider_rate_limited_after_exhausting_retries(self):
        sleep = _RecordingSleep()
        client = _FakeClient([_FakeResponse(429) for _ in range(5)])
        with pytest.raises(ProviderRateLimitedError):
            request_json(client, "GET", "https://example.test/api", max_retries=2, sleep=sleep)

    def test_never_hammers_the_provider_beyond_max_retries(self):
        """The explicit Phase 10 requirement: do not create an
        uncontrolled retry loop."""
        sleep = _RecordingSleep()
        client = _FakeClient([_FakeResponse(429) for _ in range(100)])
        with pytest.raises(ProviderRateLimitedError):
            request_json(client, "GET", "https://example.test/api", max_retries=3, sleep=sleep)
        assert client.calls == 4  # bounded, never anywhere near 100


class TestServerErrorRetry:
    def test_5xx_retries_then_raises_provider_unavailable(self):
        sleep = _RecordingSleep()
        client = _FakeClient([_FakeResponse(503) for _ in range(5)])
        with pytest.raises(ProviderUnavailableError):
            request_json(client, "GET", "https://example.test/api", max_retries=2, sleep=sleep)
        assert client.calls == 3


class TestClientErrorNeverRetried:
    def test_a_4xx_other_than_429_fails_immediately_without_retry(self):
        sleep = _RecordingSleep()
        client = _FakeClient([_FakeResponse(404, text="not found")])
        with pytest.raises(ProviderResponseError):
            request_json(client, "GET", "https://example.test/api", sleep=sleep)
        assert client.calls == 1
        assert sleep.calls == []


class TestMalformedResponse:
    def test_malformed_json_on_a_200_raises_provider_response_error(self):
        client = _FakeClient([_FakeResponse(200, json_body=_MALFORMED)])
        with pytest.raises(ProviderResponseError):
            request_json(client, "GET", "https://example.test/api")
