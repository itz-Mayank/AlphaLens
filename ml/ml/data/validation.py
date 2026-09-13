"""ML-specific data validation. Separate from (and stricter than) the
backend's `app/services/market_data_validation.py` — that module protects
a live ingestion pipeline (drop a bad bar, keep going); this one protects a
research dataset, where the goal is to know *exactly* what's wrong with the
raw data before any cleaning happens; see `clean()` below for the one and
only transformation this module is allowed to make, and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

REQUIRED_COLUMNS = ("ticker", "ts", "open", "high", "low", "close", "volume")

# A single-day move larger than this is flagged as suspicious (e.g. an
# unadjusted stock split) but NOT removed — see docs/ml-pipeline.md
# "missing-data handling". 50% is deliberately generous: real single-day
# moves this large are rare but not impossible (earnings shocks), while an
# unadjusted 2:1 or 4:1 split would clear it easily.
SUSPICIOUS_JUMP_THRESHOLD = 0.50


@dataclass
class ValidationReport:
    row_count: int
    ticker_count: int
    missing_columns: list[str] = field(default_factory=list)
    duplicate_timestamps: list[tuple[str, str]] = field(default_factory=list)
    out_of_order: list[str] = field(default_factory=list)
    invalid_ohlc_relationship: list[tuple[str, str]] = field(default_factory=list)
    non_positive_price: list[tuple[str, str]] = field(default_factory=list)
    negative_volume: list[tuple[str, str]] = field(default_factory=list)
    missing_values: dict[str, int] = field(default_factory=dict)
    suspicious_jumps: list[tuple[str, str, float]] = field(default_factory=list)
    insufficient_history: list[tuple[str, int]] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """`True` iff nothing here would make the data unsafe to use as-is.
        Suspicious jumps are informational (documented, not blocking) —
        everything else is a hard failure."""
        return not (
            self.missing_columns
            or self.duplicate_timestamps
            or self.out_of_order
            or self.invalid_ohlc_relationship
            or self.non_positive_price
            or self.negative_volume
            or any(self.missing_values.values())
        )

    def summary(self) -> str:
        lines = [f"rows={self.row_count} tickers={self.ticker_count} clean={self.is_clean}"]
        for name in (
            "missing_columns",
            "duplicate_timestamps",
            "out_of_order",
            "invalid_ohlc_relationship",
            "non_positive_price",
            "negative_volume",
            "suspicious_jumps",
            "insufficient_history",
        ):
            value = getattr(self, name)
            if value:
                lines.append(f"{name}: {len(value)}")
        if any(self.missing_values.values()):
            lines.append(f"missing_values: {self.missing_values}")
        return "\n".join(lines)


def validate(df: pd.DataFrame, *, min_history_days: int = 252) -> ValidationReport:
    """Never mutates `df`. Never "fixes" anything — see module docstring."""
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        return ValidationReport(row_count=len(df), ticker_count=0, missing_columns=missing_columns)

    report = ValidationReport(row_count=len(df), ticker_count=df["ticker"].nunique())

    for column in ("open", "high", "low", "close", "volume"):
        missing = int(df[column].isna().sum())
        if missing:
            report.missing_values[column] = missing

    for ticker, group in df.groupby("ticker", sort=False):
        dup_mask = group["ts"].duplicated(keep=False)
        if dup_mask.any():
            report.duplicate_timestamps.extend(
                (ticker, str(ts)) for ts in group.loc[dup_mask, "ts"].unique()
            )

        ts_list = list(group["ts"])
        if ts_list != sorted(ts_list):
            report.out_of_order.append(ticker)

        if len(group) < min_history_days:
            report.insufficient_history.append((ticker, len(group)))

        ordered = group.sort_values("ts")
        for row in ordered.itertuples(index=False):
            if (
                row.high < row.low
                or row.high < row.open
                or row.high < row.close
                or row.low > row.open
                or row.low > row.close
            ):
                report.invalid_ohlc_relationship.append((ticker, str(row.ts)))
            if row.open <= 0 or row.high <= 0 or row.low <= 0 or row.close <= 0:
                report.non_positive_price.append((ticker, str(row.ts)))
            if row.volume < 0:
                report.negative_volume.append((ticker, str(row.ts)))

        prev_close = None
        for row in ordered.itertuples(index=False):
            if prev_close is not None and prev_close > 0:
                jump = abs(row.close / prev_close - 1)
                if jump > SUSPICIOUS_JUMP_THRESHOLD:
                    report.suspicious_jumps.append((ticker, str(row.ts), round(jump, 4)))
            prev_close = row.close

    return report


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """The ONE transformation this module performs: sort by (ticker, ts)
    and drop exact duplicate (ticker, ts) rows, keeping the first
    occurrence. Nothing else — no interpolation, no outlier removal, no
    forward-fill. A dataset that fails `validate()` for any reason other
    than duplicates must be investigated, not silently patched; see
    docs/ml-pipeline.md's "missing-data handling" section for why."""
    return (
        df.sort_values(["ticker", "ts"])
        .drop_duplicates(subset=["ticker", "ts"], keep="first")
        .reset_index(drop=True)
    )
