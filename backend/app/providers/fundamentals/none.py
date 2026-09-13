"""The explicit "fundamentals are not configured" provider —
`FUNDAMENTALS_PROVIDER=none` (the default). Returns `None` for every
ticker rather than raising, so callers see the same honest "unavailable"
shape they'd see for a ticker a real provider genuinely doesn't cover —
never a fabricated fact, and never a crash just because this feature
isn't turned on."""

from app.providers.base import CompanyFactsResult, FundamentalsProvider


class NoneFundamentalsProvider(FundamentalsProvider):
    def get_company_facts(self, ticker: str) -> CompanyFactsResult | None:
        return None
