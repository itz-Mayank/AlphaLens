"""Provider ABCs for external data feeds.

Grown incrementally, one ABC per phase that actually needs it — see
docs/decisions.md ADR-002 (amended). `NewsProvider` was added in Phase 7;
`FundamentalsProvider`/`MacroDataProvider` were added in Phase 10 once a
concrete, real, credential-free candidate existed for the former (SEC
EDGAR) and a documented real candidate for the latter (FRED) — not
speculatively. See docs/decisions.md's Phase 10 provider-ecosystem ADR for
the evaluation behind each choice.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class SecurityInfo:
    ticker: str
    name: str
    exchange: str
    sector: str | None
    industry: str | None
    currency: str


@dataclass(frozen=True)
class OHLCVBar:
    ts: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int


class MarketDataProvider(ABC):
    """Source of security metadata and historical daily OHLCV bars.

    Callers (services, Celery tasks) depend on this ABC only — never on a
    concrete provider — so swapping Demo Mode for a real vendor is a
    registry change (`app/providers/market_data/__init__.py`), not a change
    to any calling code. See ADR-002.
    """

    @property
    @abstractmethod
    def data_source(self) -> str:
        """`"demo"` or `"external"` — matches `app.db.models.security.
        DataSource`'s own string values exactly (this module intentionally
        has no DB import, so the contract is a bare string, not the enum
        itself). Lets a caller persisting a `Security`/`PriceBar` row label
        its provenance correctly without hardcoding an assumption about
        which provider is active — see `market_data_service.run_ingestion`,
        which previously hardcoded `DataSource.DEMO` regardless of the
        configured provider."""

    @abstractmethod
    def list_securities(self) -> list[SecurityInfo]:
        """The universe of securities this provider knows about.

        May raise `NotImplementedError` for a provider that deliberately
        doesn't enumerate one (e.g. a real vendor covering tens of
        thousands of instruments) — callers must be prepared to fall back
        to an explicit, caller-supplied ticker list plus their own
        curated metadata in that case; they must not assume this always
        succeeds."""

    @abstractmethod
    def search_securities(self, query: str, *, limit: int = 10) -> list[SecurityInfo]:
        """Real-time discovery — the opposite of `list_securities()`: instead
        of enumerating an entire (possibly nonexistent) universe up front,
        this answers "what does this provider know that matches `query`
        right now," by ticker or company name. A real vendor implements
        this against its own live symbol-search endpoint; Demo Mode
        implements it by filtering its fixed curated list. This is what
        lets a user discover and research a ticker AlphaLens has never
        ingested before, without requiring it to be pre-enumerated
        anywhere — see `market_data_service.run_ingestion`, which falls
        back to this for a ticker neither `list_securities()` nor the
        curated metadata table already knows about."""

    @abstractmethod
    def get_daily_bars(self, ticker: str, start: date, end: date) -> list[OHLCVBar]:
        """Daily OHLCV bars for `ticker` in [start, end], ordered by ts ascending.

        Returns an empty list for an unknown ticker rather than raising —
        "no data" and "invalid ticker" are both just "nothing to ingest"
        from the caller's perspective.
        """


@dataclass(frozen=True)
class NewsArticleData:
    """One article as a provider hands it over — before any DB identity,
    entity mapping, or sentiment exists. Deliberately has no full article
    body field: only a provider-supplied `summary` (or `None`) is ever
    carried, never a scraped/reconstructed full text — see
    docs/decisions.md's news-licensing ADR."""

    external_id: str
    title: str
    summary: str | None
    url: str
    publisher: str
    published_at: datetime
    language: str


class NewsProvider(ABC):
    """Source of financial news articles, optionally filtered to a set of
    tickers. Callers (services, Celery tasks) depend on this ABC only —
    never on a concrete provider — so swapping Demo Mode for a real vendor
    is a registry change (`app/providers/news/__init__.py`), not a change
    to any calling code (same pattern as `MarketDataProvider`, ADR-002).
    """

    @property
    @abstractmethod
    def data_source(self) -> str:
        """`"demo"` or `"external"` — matches `app.db.models.news.
        NewsDataSource`'s own string values; see `MarketDataProvider.
        data_source` for the full rationale."""

    @abstractmethod
    def fetch_articles(
        self, *, tickers: list[str] | None, since: datetime, until: datetime, limit: int
    ) -> list[NewsArticleData]:
        """Articles related to `tickers` (or this provider's general feed if
        `None`) published in `[since, until]`, newest-first, capped at
        `limit`. A pure function of its inputs — explicit `(since, until)`
        rather than reading wall-clock time internally, exactly mirroring
        `MarketDataProvider.get_daily_bars`'s explicit `(start, end)`; the
        caller (a service, never the provider itself) resolves `until` to
        "now" when a live fetch is wanted.

        Returns an empty list for an unknown ticker or a genuinely empty
        result rather than raising.
        """


@dataclass(frozen=True)
class FundamentalFact:
    """One reported financial fact, exactly as filed — never a derived
    metric (a P/E ratio, a growth rate) computed by the provider adapter
    itself; deriving anything from these is the caller's job, done only
    when it can be computed correctly (see docs/decisions.md's Phase 10
    provider-ecosystem ADR on why this boundary matters: an adapter that
    silently invents "P/E" from whatever fields happen to be present is
    indistinguishable, to everything downstream, from a real one).

    `period_start` is `None` for an instant concept (e.g. `Assets` on a
    balance-sheet date) and set for a duration concept (e.g. `Revenues`
    over a quarter) — collapsing that distinction would silently treat a
    point-in-time balance as if it were a flow over a period, or vice
    versa.
    """

    concept: str  # e.g. "Assets", "Revenues" (source taxonomy's own name)
    value: Decimal
    unit: str  # e.g. "USD", "shares" — exactly as the source reports it
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None  # e.g. "Q1", "FY"
    form: str  # e.g. "10-K", "10-Q" — the filing type this fact came from
    filed_date: date
    accession_number: str | None  # source's own filing identifier, if any


@dataclass(frozen=True)
class CompanyFactsResult:
    ticker: str
    company_name: str
    external_id: str  # source's own company identifier (e.g. a CIK)
    facts: list[FundamentalFact]
    retrieved_at: datetime


class FundamentalsProvider(ABC):
    """Source of as-filed company fundamental facts (revenue, assets,
    liabilities, cash flow, shares — never a derived ratio; see
    `FundamentalFact`). Callers depend on this ABC only, never a concrete
    vendor SDK, matching `MarketDataProvider`/`NewsProvider`'s pattern
    (ADR-002)."""

    @abstractmethod
    def get_company_facts(self, ticker: str) -> CompanyFactsResult | None:
        """All available facts for `ticker`, or `None` if the provider has
        no record of it (an unknown ticker, never an exception) — the same
        "unknown is an empty/None result, not a raised error" convention
        `MarketDataProvider.get_daily_bars` already establishes."""


@dataclass(frozen=True)
class MacroObservationData:
    """One economic-indicator observation. `observation_date` (the period
    the value actually describes) is kept structurally separate from
    `retrieved_at` (when this deployment fetched it) specifically so nothing
    downstream can conflate "when this was true" with "when we learned it"
    — the exact look-ahead-bias risk Phase 10 explicitly calls out for
    macro data. `vintage_date`, when a provider supplies one (FRED calls
    this `realtime_start`), is the date this specific value was first
    published/known — a later-revised figure (common for GDP/CPI) gets a
    new vintage, not a silent overwrite of history."""

    series_id: str  # source's own series identifier, e.g. "FEDFUNDS"
    observation_date: date
    value: Decimal | None  # None for a real "no data this period" gap — never 0
    unit: str
    frequency: str  # e.g. "Monthly", "Quarterly"
    vintage_date: date | None


class MacroDataProvider(ABC):
    """Source of macroeconomic indicator observations, independent of any
    security. Callers depend on this ABC only, never a concrete vendor SDK
    (ADR-002)."""

    @abstractmethod
    def get_observations(
        self, series_id: str, *, start: date, end: date
    ) -> list[MacroObservationData]:
        """Observations for `series_id` with `observation_date` in
        `[start, end]`, ordered ascending. Returns an empty list for an
        unknown series rather than raising."""
