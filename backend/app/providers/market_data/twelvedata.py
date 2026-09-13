"""Twelve Data market-data provider — real, selected after comparing it
against Alpha Vantage (25 requests/day free — impractical for any real
ingestion cycle) and Finnhub (historical OHLCV candles were moved to paid
tiers; free keys get a 403 on exactly the endpoint AlphaLens needs). See
docs/decisions.md's Phase 10 provider-ecosystem ADR for the full
comparison and the licensing caveat this adapter's docstring repeats
below.

**Licensing note (verified against Twelve Data's own Terms of Use, not a
third-party summary)**: the free tier explicitly prohibits commercial use
and redistribution (Section 2.3). That's acceptable for this project's own
demo/personal deployment; it is NOT acceptable if this deployment were
ever operated as a commercial product without upgrading to a paid plan —
documented here so that boundary is never silently crossed.

Requires `TWELVE_DATA_API_KEY`, which this deployment does not have
configured by default — the adapter boundary is built and unit-tested
against mocked responses; no live validation was performed in this
session (see the ADR).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from app.providers.base import MarketDataProvider, OHLCVBar, SecurityInfo
from app.providers.http_client import ProviderRateLimitedError, ProviderResponseError, request_json

TIME_SERIES_URL = "https://api.twelvedata.com/time_series"
SYMBOL_SEARCH_URL = "https://api.twelvedata.com/symbol_search"

# Twelve Data's symbol_search covers every instrument type it knows about
# (stocks, ETFs, forex, crypto, mutual funds, bonds...) — AlphaLens is an
# equity research product, so results are filtered to these two
# instrument_type values (confirmed against Twelve Data's own
# documentation examples, not guessed) rather than surfacing e.g. a forex
# pair or a bond from the same search response.
_EQUITY_INSTRUMENT_TYPES = frozenset({"Common Stock", "ETF"})


class TwelveDataMarketDataProvider(MarketDataProvider):
    """`list_securities` is intentionally NOT implemented against Twelve
    Data's `/stocks` reference endpoint (tens of thousands of instruments
    across every exchange it covers) — AlphaLens ingests a small,
    deliberately curated ticker list (see `ExperimentConfig.tickers` /
    ingestion request payloads), never "every instrument a vendor knows
    about," so this always raises rather than silently returning a huge or
    arbitrary universe. `get_daily_bars` is the method Phase 10 actually
    needs and the one this adapter implements for real.
    """

    def __init__(self, *, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError(
                "Twelve Data requires an API key (TWELVE_DATA_API_KEY) — register free at "
                "https://twelvedata.com/pricing."
            )
        self._api_key = api_key
        self._client = client or httpx.Client()

    @property
    def data_source(self) -> str:
        return "external"

    def list_securities(self) -> list[SecurityInfo]:
        raise NotImplementedError(
            "TwelveDataMarketDataProvider does not enumerate a universe — AlphaLens ingests an "
            "explicit, curated ticker list, never Twelve Data's full instrument reference."
        )

    def search_securities(self, query: str, *, limit: int = 10) -> list[SecurityInfo]:
        query = query.strip()
        if not query:
            return []
        params = {"symbol": query, "outputsize": min(max(limit, 1), 120), "apikey": self._api_key}
        body = request_json(self._client, "GET", SYMBOL_SEARCH_URL, params=params)

        if isinstance(body, dict) and body.get("status") == "error":
            code = body.get("code")
            if code == 429:
                raise ProviderRateLimitedError(f"Twelve Data rate limit: {body.get('message')}")
            if code == 401:
                raise ProviderResponseError(
                    f"Twelve Data authentication failed: {body.get('message')}"
                )
            return []

        if not isinstance(body, dict) or "data" not in body:
            raise ProviderResponseError(f"Malformed Twelve Data symbol_search response: {body!r}")

        results: list[SecurityInfo] = []
        seen_tickers: set[str] = set()
        for raw in body["data"]:
            info = self._parse_search_result(raw)
            if info is None or info.ticker in seen_tickers:
                continue
            seen_tickers.add(info.ticker)
            results.append(info)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _parse_search_result(raw: dict) -> SecurityInfo | None:
        """A malformed or non-equity row is skipped, never fatal to the
        whole search — mirrors `_parse_bar`'s per-item leniency."""
        if not isinstance(raw, dict):
            return None
        if raw.get("instrument_type") not in _EQUITY_INSTRUMENT_TYPES:
            return None
        try:
            return SecurityInfo(
                ticker=str(raw["symbol"]).upper(),
                name=str(raw["instrument_name"]),
                exchange=str(raw["exchange"]),
                sector=None,  # symbol_search doesn't report sector/industry
                industry=None,
                currency=str(raw.get("currency") or "USD"),
            )
        except (KeyError, TypeError):
            return None

    def get_daily_bars(self, ticker: str, start: date, end: date) -> list[OHLCVBar]:
        params = {
            "symbol": ticker.upper(),
            "interval": "1day",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "apikey": self._api_key,
            "outputsize": 5000,
            "order": "ASC",
        }
        body = request_json(self._client, "GET", TIME_SERIES_URL, params=params)

        if isinstance(body, dict) and body.get("status") == "error":
            # Twelve Data returns 200 with a `{"status": "error", ...}`
            # body for an unknown symbol — treated the same as "no data,"
            # matching every other provider's "unknown ticker -> empty
            # list, never an exception" convention, EXCEPT for the two
            # error codes that mean something the caller must actually see
            # (rate limited / invalid key) rather than silently swallow.
            code = body.get("code")
            if code == 429:
                raise ProviderRateLimitedError(f"Twelve Data rate limit: {body.get('message')}")
            if code == 401:
                raise ProviderResponseError(
                    f"Twelve Data authentication failed: {body.get('message')}"
                )
            return []

        if not isinstance(body, dict) or "values" not in body:
            raise ProviderResponseError(f"Malformed Twelve Data response for {ticker!r}")

        bars: list[OHLCVBar] = []
        for raw in body["values"]:
            bar = self._parse_bar(raw)
            if bar is not None:
                bars.append(bar)
        bars.sort(key=lambda b: b.ts)
        return bars

    @staticmethod
    def _parse_bar(raw: dict) -> OHLCVBar | None:
        """A malformed individual bar is skipped, never fatal to the whole
        batch — `market_data_validation.validate_bars` re-validates
        everything this returns anyway, so this parse step only needs to
        reject what it structurally cannot represent."""
        try:
            ts = date.fromisoformat(raw["datetime"][:10])
            open_ = Decimal(str(raw["open"]))
            high = Decimal(str(raw["high"]))
            low = Decimal(str(raw["low"]))
            close = Decimal(str(raw["close"]))
            volume = int(raw.get("volume") or 0)
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return None
        return OHLCVBar(
            ts=ts,
            open=open_,
            high=high,
            low=low,
            close=close,
            adjusted_close=close,  # Twelve Data's free tier doesn't split-adjust separately
            volume=volume,
        )
