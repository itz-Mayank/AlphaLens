"""Trend features: moving averages and price-relative-to-average ratios."""

from __future__ import annotations

import pandas as pd


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, center=False, min_periods=window).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    """`adjust=False`: the standard recursive EMA definition (each value is
    a function of the previous EMA and the current price only), not
    pandas' default "as if computed from the start with full weights"
    variant — the recursive form is what every charting platform means by
    EMA and is more stable for use as a running feature."""
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


def price_to_sma(close: pd.Series, window: int) -> pd.Series:
    """`close[t] / SMA(t) - 1` — how far price has moved from its trailing
    average, as a fraction."""
    return close / sma(close, window) - 1


def price_to_ema(close: pd.Series, span: int) -> pd.Series:
    return close / ema(close, span) - 1
