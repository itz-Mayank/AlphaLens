"""Demo Mode news: the same real, well-known ticker universe
`DemoMarketDataProvider` uses, with entirely SYNTHETIC headlines (templated,
not real news, not scraped from anywhere) — this is Demo Mode, not a claim
about real news. Every stored article is labeled `data_source="demo"` —
see docs/decisions.md's news ADRs and ADR-007's original precedent for
`Security`. Article URLs use the `.invalid` TLD (reserved by RFC 2606 for
non-resolving example domains) so a clicked demo link fails obviously
rather than silently resolving somewhere unintended.

Determinism: `fetch_articles(tickers, since, until, limit)` is a pure
function of its inputs, mirroring `DemoMarketDataProvider.get_daily_bars`'s
explicit `(start, end)` contract (never reads wall-clock time internally)
— the same call returns byte-identical articles every time, which is what
makes re-ingesting the same window a meaningful idempotency test rather
than a coincidence.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.providers.base import NewsArticleData, NewsProvider

_UNIVERSE = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "JPM", "XOM", "JNJ")

_COMPANY_NAMES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com, Inc.",
    "NVDA": "NVIDIA Corporation",
    "TSLA": "Tesla, Inc.",
    "META": "Meta Platforms, Inc.",
    "JPM": "JPMorgan Chase & Co.",
    "XOM": "Exxon Mobil Corporation",
    "JNJ": "Johnson & Johnson",
}

# Deliberately mixed sentiment leanings (earnings beat, guidance miss,
# routine/neutral announcements) so a real FinBERT run over this fixture
# produces a genuinely varied sentiment distribution rather than one label
# every time.
_HEADLINE_TEMPLATES = (
    "{name} reports quarterly earnings that beat analyst expectations, shares rise",
    "{name} shares tumble after disappointing revenue guidance",
    "{name} announces new product lineup at industry conference",
    "{name} faces regulatory scrutiny over business practices",
    "{name} to hold annual shareholder meeting next month",
    "Analysts raise price target on {name} stock citing strong fundamentals",
    "{name} stock volatile amid broader market uncertainty",
    "{name} announces executive leadership change",
)

_SUMMARY_TEMPLATES = (
    "The company's latest quarterly results topped Wall Street estimates, driven by strong demand.",
    "Investors reacted negatively to the company's updated outlook for the coming quarter.",
    "The announcement was made at a major industry event attended by press and analysts.",
    "Regulators are reviewing the company's practices following recent complaints.",
    "Shareholders will vote on several proposals during the scheduled meeting.",
    "Several analysts adjusted their models following the company's recent performance.",
    "Trading volume was elevated as broader market conditions weighed on the stock.",
    "The change is part of a broader reorganization announced by the company.",
)

_PUBLISHERS = ("Demo Wire", "Demo Markets Daily", "Demo Financial Times")


def _seed_for(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


class DemoNewsProvider(NewsProvider):
    @property
    def data_source(self) -> str:
        return "demo"

    def fetch_articles(
        self, *, tickers: list[str] | None, since: datetime, until: datetime, limit: int
    ) -> list[NewsArticleData]:
        if until <= since:
            return []

        target_tickers = [t.upper() for t in tickers] if tickers else list(_UNIVERSE)
        target_tickers = [t for t in target_tickers if t in _COMPANY_NAMES]

        articles: list[NewsArticleData] = []
        for ticker in target_tickers:
            name = _COMPANY_NAMES[ticker]
            for template_index, (headline_template, summary_template) in enumerate(
                zip(_HEADLINE_TEMPLATES, _SUMMARY_TEMPLATES, strict=True)
            ):
                # Deterministic position within [since, until] — a pure
                # function of (ticker, template_index), never of wall-clock
                # time, so the same window always yields the same relative
                # placement regardless of when the call actually happens.
                fraction = (_seed_for(ticker, str(template_index)) % 1000) / 1000
                published_at = since + (until - since) * fraction
                publisher = _PUBLISHERS[
                    _seed_for(ticker, str(template_index), "publisher") % len(_PUBLISHERS)
                ]

                articles.append(
                    NewsArticleData(
                        external_id=f"{ticker}-{template_index}",
                        title=headline_template.format(name=name),
                        summary=summary_template,
                        url=f"https://demo-news.invalid/{ticker.lower()}/{template_index}",
                        publisher=publisher,
                        published_at=published_at,
                        language="en",
                    )
                )

        articles.sort(key=lambda a: a.published_at, reverse=True)
        return articles[:limit]
