"""OHLCV data-quality checks, run on every bar before it's persisted.

Invalid bars are dropped, not corrected and not allowed to fail the whole
ingestion job — one bad bar from a provider shouldn't block 500 good ones.
The job's `metadata` records how many were dropped and why (see
market_data_service.py) so bad data is visible, not silently swallowed.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.providers.base import OHLCVBar


class ValidationSeverity:
    """REJECTED bars are dropped before persistence (see `validate_bars`).
    WARNING findings (Phase 10 — `detect_price_warnings`) never block
    ingestion; they're informational, recorded in job metadata for a human
    to look at, since a real single-day move this large is sometimes
    genuine (earnings, a stock split) and sometimes a provider data-quality
    bug — this module can't tell which, so it flags rather than guesses."""

    WARNING = "WARNING"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ValidationIssue:
    ts: date
    reason: str


def validate_bar(bar: OHLCVBar, *, as_of: date | None = None) -> str | None:
    """Returns the first violated-rule description, or None if the bar is
    valid. `as_of` (defaults to today) bounds how far in the future a bar's
    own date may be — a provider bug or corrupted feed sending a
    not-yet-real trading day is rejected, never silently ingested."""
    if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0 or bar.adjusted_close <= 0:
        return "non_positive_price"
    if bar.volume < 0:
        return "negative_volume"
    if bar.low > bar.high:
        return "low_greater_than_high"
    if bar.open > bar.high or bar.close > bar.high:
        return "open_or_close_above_high"
    if bar.open < bar.low or bar.close < bar.low:
        return "open_or_close_below_low"
    if bar.ts > (as_of or date.today()):
        return "future_timestamp"
    return None


def validate_bars(
    bars: list[OHLCVBar], *, as_of: date | None = None
) -> tuple[list[OHLCVBar], list[ValidationIssue]]:
    """Splits `bars` into (valid, issues). Also flags duplicate timestamps
    within the same batch — a provider bug, not something the DB unique
    constraint alone should have to catch. Every issue here is REJECTED-
    tier (the bar is dropped, not persisted) — see `detect_price_warnings`
    for the separate WARNING tier that never drops anything."""
    valid: list[OHLCVBar] = []
    issues: list[ValidationIssue] = []
    seen_timestamps: set[date] = set()

    for bar in bars:
        if bar.ts in seen_timestamps:
            issues.append(ValidationIssue(bar.ts, "duplicate_timestamp_in_batch"))
            continue
        reason = validate_bar(bar, as_of=as_of)
        if reason is not None:
            issues.append(ValidationIssue(bar.ts, reason))
            continue
        seen_timestamps.add(bar.ts)
        valid.append(bar)

    return valid, issues


def detect_price_warnings(
    bars: list[OHLCVBar], *, threshold: float = 0.5
) -> list[ValidationIssue]:
    """Flags a day-over-day close-to-close move exceeding `threshold`
    (50% by default) as a WARNING — informational only, never dropped from
    `bars` and never blocking ingestion (see `ValidationSeverity`'s
    docstring for why: this module has no way to distinguish a genuine
    large move from a bad print). `bars` must already be chronologically
    sorted (the same order `validate_bars`'/the provider's output is in);
    this function does no sorting of its own."""
    warnings: list[ValidationIssue] = []
    for previous, current in zip(bars, bars[1:], strict=False):
        if previous.close <= 0:
            continue
        change = abs((current.close - previous.close) / previous.close)
        if change > threshold:
            warnings.append(
                ValidationIssue(current.ts, f"abnormal_price_move_{float(change):.2f}")
            )
    return warnings


def detect_gaps(bars: list[OHLCVBar]) -> list[date]:
    """Business days between the first and last bar with no bar at all.
    Informational only (recorded in job metadata) — never blocks ingestion,
    since a real market also has holidays this simple weekday check doesn't
    know about.
    """
    if len(bars) < 2:
        return []

    present = {bar.ts for bar in bars}
    gaps: list[date] = []
    current = bars[0].ts
    last = bars[-1].ts
    while current <= last:
        if current.weekday() < 5 and current not in present:
            gaps.append(current)
        current += timedelta(days=1)
    return gaps
