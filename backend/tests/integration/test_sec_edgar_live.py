"""A genuine live validation against the real SEC EDGAR API — the ONE real
external data provider in this project that needs no credential, so it is
the only one that can be honestly validated live in a normal development
environment (Twelve Data/FRED both need a registered key this deployment
does not have; see docs/decisions.md's Phase 10 provider-ecosystem ADR).

Excluded from the default `pytest` run (`addopts = "-m 'not live_provider'"`
in pyproject.toml) — run explicitly:

    pytest -m live_provider tests/integration/test_sec_edgar_live.py

Makes a real network call to data.sec.gov. If SEC EDGAR is unreachable
(network policy, an outage, a CI sandbox with no internet egress) the test
is skipped, not failed — this is a live-environment check, not a
correctness assertion that must always pass in every execution context.
"""

from __future__ import annotations

import httpx
import pytest
from app.providers.fundamentals.sec_edgar import SECEdgarFundamentalsProvider

pytestmark = pytest.mark.live_provider

_USER_AGENT = "AlphaLens live-provider-test alphalens-dev@example.com"


def _sec_edgar_reachable() -> bool:
    try:
        response = httpx.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": _USER_AGENT},
            timeout=10.0,
        )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(
    not _sec_edgar_reachable(), reason="SEC EDGAR unreachable from this environment"
)
class TestSECEdgarLive:
    def test_fetches_real_apple_company_facts(self):
        provider = SECEdgarFundamentalsProvider(user_agent=_USER_AGENT)
        result = provider.get_company_facts("AAPL")

        assert result is not None
        assert result.ticker == "AAPL"
        assert "apple" in result.company_name.lower()
        assert result.external_id == "CIK0000320193"
        assert len(result.facts) > 0

        # Every fact must carry real provenance, never a fabricated/blank
        # value — the exact guarantee this whole provider exists to keep.
        for fact in result.facts:
            assert fact.form
            assert fact.filed_date is not None
            assert fact.period_end is not None

    def test_unknown_ticker_returns_none_not_an_exception(self):
        provider = SECEdgarFundamentalsProvider(user_agent=_USER_AGENT)
        assert provider.get_company_facts("ZZZZZ_NOT_A_REAL_TICKER") is None
