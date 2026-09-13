"""Maps article text to canonical securities — the existing `securities`
table is the only source of truth for what a "known company" is. No
external NER model: at this project's scale (a handful of tracked
securities), two precise, explainable, deterministic signals cover the
real cases and — more importantly — fail closed on the ambiguous ones
(see docs/decisions.md's entity-mapping ADR for why this is the right
scope rather than a corner cut).

Two match methods, combined rather than used alone (never "naive string
matching as the only mechanism"):

1. **`TICKER_SYMBOL`** (confidence 0.95) — an explicit `$AAPL` cashtag or
   `(AAPL)` parenthetical mention. Ticker symbols are short, capitalized,
   and specifically marked as tickers by their surrounding punctuation —
   about as unambiguous as text matching gets.
2. **`COMPANY_NAME`** (confidence 0.70) — the security's legal name with
   common corporate suffixes stripped (", Inc.", " Corporation", etc.),
   matched **case-sensitively** with a word boundary. Case-sensitivity is
   the deliberate mitigation for exactly the failure mode the spec warns
   about: "Apple Inc." strips to the core name "Apple" — an ordinary
   English word (the fruit) as well as a company. Matching only the
   properly-capitalized form ("Apple", not "apple") rejects the fruit
   while still matching how real financial journalism actually writes the
   company's name in running text ("Apple reported record iPhone sales").
   Core names shorter than `MIN_CORE_NAME_LENGTH` are skipped entirely —
   too short to be a confident, low-false-positive-rate signal by
   themselves.

Never returns a match below `MIN_CONFIDENCE` — an article this function
can't confidently place stays unmapped rather than getting an invented
ticker.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.db.models.news import EntityMatchMethod
from app.db.models.security import Security
from app.repositories.news_repository import EntityMatch

TICKER_SYMBOL_CONFIDENCE = Decimal("0.95")
COMPANY_NAME_CONFIDENCE = Decimal("0.70")
MIN_CONFIDENCE = Decimal("0.70")
MIN_CORE_NAME_LENGTH = 4

_CORPORATE_SUFFIXES = (
    ", Incorporated",
    " Incorporated",
    ", Inc.",
    " Inc.",
    ", Corp.",
    " Corp.",
    " Corporation",
    ", Co.",
    " & Co.",
    " Co.",
    " Company",
    ", Ltd.",
    " Ltd.",
    " Limited",
    ", LLC",
    " LLC",
    " plc",
)


def _core_company_name(full_name: str) -> str:
    """Strips one trailing corporate suffix at a time until none match —
    handles a name with a compound suffix like "..., Inc." (comma + Inc.)
    without needing every combination spelled out."""
    name = full_name
    changed = True
    while changed:
        changed = False
        for suffix in _CORPORATE_SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                changed = True
                break
    return name.strip()


def _ticker_mention_pattern(ticker: str) -> re.Pattern[str]:
    escaped = re.escape(ticker)
    return re.compile(rf"\$\s?{escaped}\b|\(\s?{escaped}\s?\)", re.IGNORECASE)


def _company_name_pattern(core_name: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(core_name)}\b")  # case-sensitive, deliberately


def extract_entities(text: str, securities: list[Security]) -> list[EntityMatch]:
    """Returns one `EntityMatch` per security confidently found in `text` —
    zero, one, or several (an article can legitimately be about more than
    one company). Never fabricates a match for a security not actually
    referenced."""
    matches: dict[int, EntityMatch] = {}

    for security in securities:
        if _ticker_mention_pattern(security.ticker).search(text):
            matches[security.id] = EntityMatch(
                security_id=security.id,
                match_method=EntityMatchMethod.TICKER_SYMBOL,
                confidence=TICKER_SYMBOL_CONFIDENCE,
            )
            continue

        core_name = _core_company_name(security.name)
        if len(core_name) < MIN_CORE_NAME_LENGTH:
            continue
        if _company_name_pattern(core_name).search(text):
            matches[security.id] = EntityMatch(
                security_id=security.id,
                match_method=EntityMatchMethod.COMPANY_NAME,
                confidence=COMPANY_NAME_CONFIDENCE,
            )

    return [m for m in matches.values() if m.confidence >= MIN_CONFIDENCE]
