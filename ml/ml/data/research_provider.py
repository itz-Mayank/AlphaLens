"""Research-data providers. Structurally separate from
`backend/app/providers/market_data/` on purpose — `ml/` must not import
`backend/` (it's a standalone package, ADR-001), and a research dataset has
a different shape anyway (a full historical panel loaded once, not a
per-ticker "give me bars for [start, end]" call used by a live app).

`ResearchDataProvider` is the ABC; `SampleSP500ResearchProvider` is the one
implementation today, backed by the real, provenance-tracked CSV in
`ml/data/sample_data/` (see PROVENANCE.md there). A future real-vendor
provider (e.g. a paid historical-data API) plugs in behind the same ABC
without changing any downstream feature/dataset/model code — the same
pattern as the backend's `MarketDataProvider` (docs/decisions.md ADR-002).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ml.data.contracts import RESEARCH_DATASET_VERSION, DataEnvironment, DatasetProvenance

_SAMPLE_DATA_PATH = Path(__file__).parent / "sample_data" / "research_sample_sp500.csv"

REQUIRED_COLUMNS = ("ticker", "ts", "open", "high", "low", "close", "volume")


class ResearchDataProvider(ABC):
    """Loads a historical OHLCV panel for research use, with provenance."""

    @abstractmethod
    def load(
        self, tickers: tuple[str, ...] | None = None
    ) -> tuple[pd.DataFrame, DatasetProvenance]:
        """Returns (panel, provenance). `panel` has columns
        `REQUIRED_COLUMNS`, sorted by (ticker, ts) ascending, with no
        duplicate (ticker, ts) pairs. `tickers=None` returns every ticker
        this provider has."""


class SampleSP500ResearchProvider(ResearchDataProvider):
    """Real historical data (11 S&P 500 constituents, 2013-02-08 to
    2018-02-07) from a permissively-licensed public source — see
    `ml/data/sample_data/PROVENANCE.md` for exactly where it came from and
    what was and wasn't done to it. This is a fixed, versioned snapshot,
    not a live feed."""

    def __init__(self, csv_path: Path = _SAMPLE_DATA_PATH):
        self._csv_path = csv_path

    def load(
        self, tickers: tuple[str, ...] | None = None
    ) -> tuple[pd.DataFrame, DatasetProvenance]:
        df = pd.read_csv(self._csv_path, parse_dates=["date"])
        df = df.rename(columns={"date": "ts"})
        df["ts"] = df["ts"].dt.date

        if tickers is not None:
            unknown = set(tickers) - set(df["ticker"].unique())
            if unknown:
                raise ValueError(f"Unknown ticker(s) for this provider: {sorted(unknown)}")
            df = df[df["ticker"].isin(tickers)]

        df = df.sort_values(["ticker", "ts"]).reset_index(drop=True)
        df = df[list(REQUIRED_COLUMNS)]

        resolved_tickers = tuple(sorted(df["ticker"].unique()))
        provenance = DatasetProvenance(
            source="plotly/datasets:all_stocks_5yr.csv (MIT license, real S&P 500 OHLCV)",
            environment=DataEnvironment.RESEARCH,
            tickers=resolved_tickers,
            start_date=df["ts"].min(),
            end_date=df["ts"].max(),
            retrieved_at=datetime(2026, 9, 11, tzinfo=UTC),
            dataset_version=RESEARCH_DATASET_VERSION,
            notes="See ml/data/sample_data/PROVENANCE.md for full extraction methodology.",
        )
        return df, provenance
