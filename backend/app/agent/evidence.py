"""The evidence model — every factual claim the agent makes must trace
back to one of these. `app/agent/tools.py` produces `Evidence` alongside
every tool's structured result; `app/agent/orchestrator.py` collects it
across the whole conversation turn and returns it verbatim to the API
layer, so a citation like `[Forecast]` in the final answer always has a
corresponding, inspectable `Evidence` entry behind it — never a bare
assertion with nothing to check it against.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


class EvidenceSourceType:
    MARKET_DATA = "MARKET_DATA"
    FORECAST = "FORECAST"
    SHAP = "SHAP"
    NEWS = "NEWS"
    SENTIMENT = "SENTIMENT"
    BACKTEST = "BACKTEST"
    WATCHLIST = "WATCHLIST"
    SCREENER = "SCREENER"
    PORTFOLIO = "PORTFOLIO"
    ALERT = "ALERT"
    FUNDAMENTALS = "FUNDAMENTALS"
    MACRO = "MACRO"
    SYSTEM = "SYSTEM"

    ALL = (
        MARKET_DATA, FORECAST, SHAP, NEWS, SENTIMENT, BACKTEST,
        WATCHLIST, SCREENER, PORTFOLIO, ALERT, FUNDAMENTALS, MACRO, SYSTEM,
    )


_DISPLAY_NAMES = {
    EvidenceSourceType.MARKET_DATA: "Market Data",
    EvidenceSourceType.FORECAST: "Forecast",
    EvidenceSourceType.SHAP: "SHAP",
    EvidenceSourceType.NEWS: "News",
    EvidenceSourceType.SENTIMENT: "Sentiment",
    EvidenceSourceType.BACKTEST: "Backtest",
    EvidenceSourceType.WATCHLIST: "Watchlist",
    EvidenceSourceType.SCREENER: "Screener",
    EvidenceSourceType.PORTFOLIO: "Portfolio",
    EvidenceSourceType.ALERT: "Alert",
    EvidenceSourceType.FUNDAMENTALS: "Fundamentals",
    EvidenceSourceType.MACRO: "Macro",
    EvidenceSourceType.SYSTEM: "System",
}


@dataclass(frozen=True)
class Evidence:
    source_type: str  # one of EvidenceSourceType.ALL
    source_id: str  # a natural key for this evidence, e.g. a tool-call id or article URL
    ticker: str | None
    timestamp: datetime
    data: dict[str, Any]  # the tool's own structured output — never re-derived/summarized here
    provenance: str  # human-readable origin, e.g. "xgboost_direction-v3" or an article URL

    def as_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "ticker": self.ticker,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "provenance": self.provenance,
        }

    def citation_tag(self) -> str:
        """The short `[Forecast]`-style tag used inline in the agent's
        final answer — see `docs/decisions.md`'s citation-format ADR."""
        return f"[{_DISPLAY_NAMES.get(self.source_type, self.source_type.title())}]"
