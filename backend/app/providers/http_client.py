"""Shared HTTP request helper for real external provider adapters (SEC
EDGAR, Twelve Data, FRED) — bounded retries with exponential backoff,
`Retry-After` respected on 429, never an uncontrolled retry loop. Written
once here rather than duplicated per adapter, so every real provider gets
the same disciplined failure behavior (Phase 10 §11/§12): a provider
timeout gets a bounded retry, a rate limit is respected rather than
hammered, a malformed response is rejected rather than silently patched
over, and nothing here ever fabricates a fallback value.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 10.0


class ProviderError(Exception):
    """Base for every controlled provider failure — adapters/services catch
    this family and map it to a clean, structured application error, never
    a raw `httpx` exception reaching a caller."""


class ProviderTimeoutError(ProviderError):
    pass


class ProviderRateLimitedError(ProviderError):
    def __init__(self, message: str, *, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailableError(ProviderError):
    """5xx or a connection-level failure after exhausting retries — the
    provider itself is down, not a data-quality problem."""


class ProviderResponseError(ProviderError):
    """A 2xx response whose body is malformed or not the expected shape —
    a real data-quality problem, never silently patched over or guessed
    at by the caller."""


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict | list:
    """One real HTTP call with a bounded retry/backoff policy. `sleep` is
    injectable so tests can assert on backoff behavior without an actual
    real-time delay — never mocked away entirely, since the retry *count*
    and *decision* are exactly what's under test.
    """
    attempt = 0
    while True:
        try:
            response = client.request(
                method, url, params=params, headers=headers, timeout=timeout_seconds
            )
        except httpx.TimeoutException as exc:
            attempt += 1
            if attempt > max_retries:
                raise ProviderTimeoutError(
                    f"Timed out calling {url} after {max_retries} retries"
                ) from exc
            sleep(backoff_seconds * (2 ** (attempt - 1)))
            continue
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Network error calling {url}: {exc}") from exc

        if response.status_code == 429:
            attempt += 1
            retry_after = response.headers.get("Retry-After")
            if attempt > max_retries:
                raise ProviderRateLimitedError(
                    f"Rate limited by {url}",
                    retry_after_seconds=float(retry_after) if retry_after else None,
                )
            wait = float(retry_after) if retry_after else backoff_seconds * (2 ** (attempt - 1))
            sleep(wait)
            continue

        if 500 <= response.status_code < 600:
            attempt += 1
            if attempt > max_retries:
                raise ProviderUnavailableError(
                    f"{url} returned {response.status_code} after {max_retries} retries"
                )
            sleep(backoff_seconds * (2 ** (attempt - 1)))
            continue

        if response.status_code >= 400:
            raise ProviderResponseError(
                f"{url} returned {response.status_code}: {response.text[:200]!r}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderResponseError(f"{url} returned malformed JSON") from exc
