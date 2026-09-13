"""Calendar features. Pure functions of the timestamp itself — trivially
leakage-free (no dependency on any other row), included for completeness
against the Phase 5 feature checklist."""

from __future__ import annotations

import pandas as pd


def day_of_week(ts: pd.Series) -> pd.Series:
    """0 = Monday .. 4 = Friday (trading days only, per the data)."""
    return pd.to_datetime(ts).dt.dayofweek


def month(ts: pd.Series) -> pd.Series:
    """1-12."""
    return pd.to_datetime(ts).dt.month


def trading_day_position_in_month(ts: pd.Series) -> pd.Series:
    """1-indexed position of this row within its (ticker's) calendar month,
    counting only the trading days present in the data — e.g. the third
    trading day of a month gets 3, regardless of the calendar date. Useful
    as a rough proxy for month-start/month-end effects without hardcoding
    a trading calendar."""
    month_key = pd.to_datetime(ts).dt.to_period("M")
    return month_key.groupby(month_key).cumcount() + 1
