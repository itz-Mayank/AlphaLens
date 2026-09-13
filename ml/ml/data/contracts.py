"""The ML data contract: what environment a row of data came from, and what
provenance metadata every dataset must carry. See docs/ml-pipeline.md for
the full write-up — this module is the executable version of that contract.

Three data environments exist and must never be blurred:

- ``DEMO``       — backend/app/providers/market_data/demo.py's synthetic,
                   seeded prices. Powers the running application's Demo
                   Mode UI. Never used for ML research.
- ``RESEARCH``   — real, provenance-tracked historical data used to build
                   and evaluate models (see research_provider.py). Not
                   connected to the running application's database.
- ``PRODUCTION`` — reserved for a future real-time/live data feed once a
                   real vendor is integrated. No implementation exists yet;
                   the enum member exists so the contract has a name for it
                   from the start rather than being retrofitted later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class DataEnvironment(StrEnum):
    DEMO = "demo"
    RESEARCH = "research"
    PRODUCTION = "production"


@dataclass(frozen=True)
class OHLCVRecord:
    """One bar. Deliberately identical in shape to the backend's
    ``app.providers.base.OHLCVBar`` — not imported from there (ml/ must not
    depend on backend/), but a `ticker` field is added since research
    datasets are cross-sectional (many tickers) rather than fetched one
    ticker at a time like the backend's provider ABC.
    """

    ticker: str
    ts: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class DatasetProvenance:
    """Every dataset produced by ``ml/`` carries one of these. Required
    fields per the Phase 5 data contract: source, tickers, date range,
    retrieval/creation timestamp, and a version string."""

    source: str
    environment: DataEnvironment
    tickers: tuple[str, ...]
    start_date: date
    end_date: date
    retrieved_at: datetime
    dataset_version: str
    notes: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "environment": self.environment.value,
            "tickers": list(self.tickers),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "retrieved_at": self.retrieved_at.isoformat(),
            "dataset_version": self.dataset_version,
            "notes": self.notes,
            "extra": self.extra,
        }


# Bumped whenever `SampleSP500ResearchProvider`'s output would change for
# the same (tickers, date range) — e.g. a different source file, a
# different extraction/cleaning step. Never bumped for reasons that don't
# change the data (this file's prose, for instance).
RESEARCH_DATASET_VERSION = "research_sample_sp500_v1"
