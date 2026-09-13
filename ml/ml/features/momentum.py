"""Momentum indicators: RSI, MACD, ROC. Standard definitions, trailing-only
(each uses only `close[..t]`)."""

from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. Wilder smoothing is itself an exponential moving
    average with `alpha = 1/period` — using `.ewm(alpha=..., adjust=False)`
    (recursive form, see trend.ema) rather than a simple rolling mean of
    gains/losses, which is the textbook-correct definition, not an
    approximation of it."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns `(macd_line, signal_line, histogram)`."""
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def roc(close: pd.Series, window: int = 10) -> pd.Series:
    """Rate of change, as a percentage: `(close[t]/close[t-window] - 1) * 100`."""
    return close.pct_change(periods=window) * 100
