"""Volatility features: rolling return volatility, Average True Range,
Bollinger Bands. All trailing-only."""

from __future__ import annotations

import pandas as pd


def rolling_volatility(close: pd.Series, window: int) -> pd.Series:
    """Trailing standard deviation of daily simple returns over `window`
    bars — a standard realized-volatility proxy."""
    return close.pct_change().rolling(window=window, center=False, min_periods=window).std()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range, Wilder-smoothed (same recursive EMA form as
    `momentum.rsi` — the textbook definition)."""
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def bollinger_bands(
    close: pd.Series, window: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns `(upper, middle, lower)`. `middle` is the SMA; `upper`/`lower`
    are `middle +/- num_std * trailing_std`."""
    middle = close.rolling(window=window, center=False, min_periods=window).mean()
    std = close.rolling(window=window, center=False, min_periods=window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def bollinger_percent_b(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series:
    """Where `close` sits within the bands, in [0, 1] under normal
    conditions (can exceed that range when price is outside the bands):
    `(close - lower) / (upper - lower)`."""
    upper, _, lower = bollinger_bands(close, window=window, num_std=num_std)
    return (close - lower) / (upper - lower)
