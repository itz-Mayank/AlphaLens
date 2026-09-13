"""FRED (Federal Reserve Economic Data) macro provider — real, well-
documented, public-domain data, but requires a free registered API key
(https://fred.stlouisfed.org/docs/api/api_key.html) this deployment does
not have configured by default. See docs/decisions.md's Phase 10
provider-ecosystem ADR: the adapter boundary is built and unit-tested
against mocked responses, but no live validation was performed in this
session (no key was available) — never fabricated.

`vintage_date` (FRED's `realtime_start`) is preserved specifically so a
later-revised figure (common for GDP/CPI) is a new vintage, never a silent
overwrite of what was known at an earlier point in time — the exact
release-vs-observation-date distinction Phase 10 requires macro data to
respect.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from app.core.logging import get_logger
from app.providers.base import MacroDataProvider, MacroObservationData
from app.providers.http_client import ProviderResponseError, request_json

logger = get_logger(__name__)

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED series carry their own native frequency; this adapter doesn't
# re-derive it, it just labels what FRED itself reports for each series id
# — a small, fixed map for the handful of series AlphaLens actually uses
# (see app/services/macro_service.py), not an attempt to cover FRED's
# entire catalog of 800,000+ series.
SERIES_FREQUENCY = {
    "FEDFUNDS": "Monthly",
    "CPIAUCSL": "Monthly",
    "UNRATE": "Monthly",
    "GDP": "Quarterly",
    "DGS10": "Daily",
}
SERIES_UNIT = {
    "FEDFUNDS": "Percent",
    "CPIAUCSL": "Index 1982-1984=100",
    "UNRATE": "Percent",
    "GDP": "Billions of Dollars",
    "DGS10": "Percent",
}


class FREDMacroProvider(MacroDataProvider):
    def __init__(self, *, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError(
                "FRED requires an API key (FRED_API_KEY) — register free at "
                "https://fred.stlouisfed.org/docs/api/api_key.html."
            )
        self._api_key = api_key
        self._client = client or httpx.Client()

    def get_observations(
        self, series_id: str, *, start: date, end: date
    ) -> list[MacroObservationData]:
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }
        body = request_json(self._client, "GET", BASE_URL, params=params)
        if not isinstance(body, dict) or "observations" not in body:
            raise ProviderResponseError(f"Malformed FRED response for series {series_id!r}")

        unit = SERIES_UNIT.get(series_id, "Unknown")
        frequency = SERIES_FREQUENCY.get(series_id, "Unknown")

        observations: list[MacroObservationData] = []
        for raw in body["observations"]:
            parsed = self._parse_observation(
                raw, series_id=series_id, unit=unit, frequency=frequency
            )
            if parsed is not None:
                observations.append(parsed)

        # Never silently hide a large number of rejected records (a
        # date-parse failure or, per FRED's own "." sentinel, a genuine
        # data gap that came back malformed rather than well-formed).
        skipped = len(body["observations"]) - len(observations)
        if skipped:
            logger.warning(
                "fred_observations_skipped", series_id=series_id,
                observations_seen=len(body["observations"]),
                observations_parsed=len(observations), observations_skipped=skipped,
            )
        return observations

    @staticmethod
    def _parse_observation(
        raw: dict, *, series_id: str, unit: str, frequency: str
    ) -> MacroObservationData | None:
        try:
            observation_date = date.fromisoformat(raw["date"])
        except (KeyError, TypeError, ValueError):
            return None  # an unparseable row is skipped, not fatal to the whole series

        # FRED represents "no data this period" as the literal string ".",
        # never a numeric 0 — preserved here as None, never coerced to 0.0.
        value: Decimal | None
        raw_value = raw.get("value")
        if raw_value in (None, ".", ""):
            value = None
        else:
            try:
                value = Decimal(str(raw_value))
            except InvalidOperation:
                value = None

        vintage_date = None
        if raw.get("realtime_start"):
            try:
                vintage_date = date.fromisoformat(raw["realtime_start"])
            except ValueError:
                vintage_date = None

        return MacroObservationData(
            series_id=series_id,
            observation_date=observation_date,
            value=value,
            unit=unit,
            frequency=frequency,
            vintage_date=vintage_date,
        )
