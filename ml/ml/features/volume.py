"""Volume features. All trailing-only."""

from __future__ import annotations

import pandas as pd


def volume_change(volume: pd.Series, periods: int = 1) -> pd.Series:
    return volume.pct_change(periods=periods)


def rolling_volume_mean(volume: pd.Series, window: int) -> pd.Series:
    return volume.rolling(window=window, center=False, min_periods=window).mean()


def rolling_volume_std(volume: pd.Series, window: int) -> pd.Series:
    return volume.rolling(window=window, center=False, min_periods=window).std()


def relative_volume(volume: pd.Series, window: int = 20) -> pd.Series:
    """Today's volume relative to its own trailing average — `> 1` means
    above-average activity. Uses the trailing mean *excluding* the current
    bar (`shift(1)` before rolling) so a single huge-volume day doesn't
    inflate its own baseline."""
    baseline = volume.shift(1).rolling(window=window, center=False, min_periods=window).mean()
    return volume / baseline
