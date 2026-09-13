"""Price/return features. Every function takes a single ticker's `close`
(and sometimes `volume`) as a chronologically-sorted `pd.Series` and returns
a same-length, same-index `pd.Series`. All rolling windows are trailing
(pandas' default — `center=False`, never overridden) so a value at row `t`
depends only on rows `<= t`. Callers (ml/features/pipeline.py) apply these
per-ticker, never across ticker boundaries.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def simple_return(close: pd.Series, periods: int = 1) -> pd.Series:
    """`close[t] / close[t-periods] - 1`."""
    return close.pct_change(periods=periods)


def log_return(close: pd.Series, periods: int = 1) -> pd.Series:
    return np.log(close / close.shift(periods))


def rolling_return(close: pd.Series, window: int) -> pd.Series:
    """Cumulative return over the trailing `window` bars ending at `t`:
    `close[t] / close[t-window] - 1`. Equivalent to `simple_return(close,
    periods=window)`, named separately since "rolling return over N days"
    and "the N-th lag return" read as different concepts to a reviewer even
    though they're the same formula."""
    return close.pct_change(periods=window)


def momentum(close: pd.Series, window: int) -> pd.Series:
    """`close[t] - close[t-window]` — the absolute-price counterpart to
    `rolling_return`'s percentage version."""
    return close.diff(periods=window)
