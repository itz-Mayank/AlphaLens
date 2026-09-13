"""SEC EDGAR fundamentals provider — real, and requiring no API key at all
(SEC's XBRL company-facts API is public; the only requirement is a
descriptive `User-Agent` header identifying the caller, per SEC's fair-
access policy). See docs/decisions.md's Phase 10 provider-ecosystem ADR
for the evaluation that selected this over every paid-fundamentals
alternative specifically because it needs no credential and can be
genuinely live-validated (see `tests/integration/test_sec_edgar_live.py`,
`@pytest.mark.live_provider`).

Never converts a filed fact into a derived metric (P/E, growth rate,
valuation ratio) — those need a price (a different provider) and a
specific, documented methodology; this module reports exactly what was
filed, nothing computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.core.logging import get_logger
from app.providers.base import CompanyFactsResult, FundamentalFact, FundamentalsProvider
from app.providers.http_client import ProviderResponseError, request_json

logger = get_logger(__name__)

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# A small, fixed, genuinely useful set of `us-gaap` taxonomy concepts —
# never "every field SEC has," which includes hundreds of company-specific
# custom tags with no consistent cross-company meaning. Chosen because
# they're the concepts most companies actually report under these exact
# names, and each maps to something AlphaLens can honestly label.
SUPPORTED_CONCEPTS = (
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "Revenues",
    "NetIncomeLoss",
    "CashAndCashEquivalentsAtCarryingValue",
    "CommonStockSharesOutstanding",
)


@dataclass(frozen=True)
class _TickerMapEntry:
    cik: int
    title: str


class SECEdgarFundamentalsProvider(FundamentalsProvider):
    def __init__(self, *, user_agent: str, client: httpx.Client | None = None):
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC EDGAR requires an identifying User-Agent with a real contact address "
                "(see SEC_EDGAR_USER_AGENT) — see SEC's fair-access policy at "
                "https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data."
            )
        self._user_agent = user_agent
        self._client = client or httpx.Client()
        self._ticker_map: dict[str, _TickerMapEntry] | None = None

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._user_agent, "Accept": "application/json"}

    def _load_ticker_map(self) -> dict[str, _TickerMapEntry]:
        """Cached for the life of this provider instance — this file is
        ~1MB and changes infrequently; re-fetching it on every
        `get_company_facts` call would be one extra real HTTP round trip
        per lookup for no benefit."""
        if self._ticker_map is not None:
            return self._ticker_map

        body = request_json(self._client, "GET", TICKER_MAP_URL, headers=self._headers())
        if not isinstance(body, dict):
            raise ProviderResponseError("SEC ticker map response was not a JSON object")

        mapping: dict[str, _TickerMapEntry] = {}
        for entry in body.values():
            try:
                ticker = str(entry["ticker"]).upper()
                mapping[ticker] = _TickerMapEntry(
                    cik=int(entry["cik_str"]), title=str(entry.get("title", ticker))
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderResponseError(f"Malformed ticker map entry: {entry!r}") from exc

        self._ticker_map = mapping
        return mapping

    def get_company_facts(self, ticker: str) -> CompanyFactsResult | None:
        ticker = ticker.upper()
        entry = self._load_ticker_map().get(ticker)
        if entry is None:
            return None

        url = COMPANY_FACTS_URL_TEMPLATE.format(cik=entry.cik)
        body = request_json(self._client, "GET", url, headers=self._headers())
        if not isinstance(body, dict) or "facts" not in body:
            raise ProviderResponseError(f"Malformed company facts response for CIK {entry.cik}")

        us_gaap = body.get("facts", {}).get("us-gaap", {})
        facts: list[FundamentalFact] = []
        seen = 0
        for concept in SUPPORTED_CONCEPTS:
            concept_data = us_gaap.get(concept)
            if not concept_data:
                continue
            for unit, entries in concept_data.get("units", {}).items():
                for raw_entry in entries:
                    seen += 1
                    fact = self._parse_entry(concept, unit, raw_entry)
                    if fact is not None:
                        facts.append(fact)

        # Never silently hide a large number of rejected records — a
        # malformed individual entry is still skipped (see `_parse_entry`),
        # but the count is always surfaced here so a real, large parse
        # failure rate is observable rather than invisible.
        skipped = seen - len(facts)
        if skipped:
            logger.warning(
                "sec_edgar_entries_skipped", ticker=ticker, cik=entry.cik,
                entries_seen=seen, entries_parsed=len(facts), entries_skipped=skipped,
            )

        return CompanyFactsResult(
            ticker=ticker,
            company_name=str(body.get("entityName", entry.title)),
            external_id=f"CIK{entry.cik:010d}",
            facts=facts,
            retrieved_at=datetime.now(UTC),
        )

    @staticmethod
    def _parse_entry(concept: str, unit: str, entry: dict) -> FundamentalFact | None:
        """A malformed individual data point is skipped, never fatal to
        the whole response — one bad entry among hundreds shouldn't lose
        every other real fact (same "drop the bad row, keep the rest"
        philosophy as `market_data_validation.validate_bars`)."""
        try:
            value = Decimal(str(entry["val"]))
            period_end = date.fromisoformat(entry["end"])
            filed_date = date.fromisoformat(entry["filed"])
            form = str(entry["form"])
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return None

        period_start = None
        if "start" in entry:
            try:
                period_start = date.fromisoformat(entry["start"])
            except (TypeError, ValueError):
                period_start = None

        return FundamentalFact(
            concept=concept,
            value=value,
            unit=unit,
            period_start=period_start,
            period_end=period_end,
            fiscal_year=entry.get("fy"),
            fiscal_period=entry.get("fp"),
            form=form,
            filed_date=filed_date,
            accession_number=entry.get("accn"),
        )
