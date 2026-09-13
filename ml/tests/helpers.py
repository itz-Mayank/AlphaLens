"""Shared synthetic-data helpers for tests. Deliberately NOT the real
sample dataset — unit tests need small, fast, fully-controlled data; the
real dataset is reserved for the (few) integration tests that exercise the
whole pipeline end to end.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_synthetic_ohlcv(
    tickers: tuple[str, ...] = ("AAA", "BBB"),
    num_days: int = 300,
    start: str = "2020-01-01",
    seed: int = 0,
) -> pd.DataFrame:
    """A small, deterministic, multi-ticker OHLCV panel — valid by
    construction (positive prices, correct OHLC relationships, no gaps,
    chronological)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=num_days)

    frames = []
    for i, ticker in enumerate(tickers):
        price = 100.0 + i * 10
        rows = []
        for ts in dates:
            daily_return = rng.normal(0.0003, 0.01)
            close = max(1.0, price * (1 + daily_return))
            open_ = price
            high = max(open_, close) * 1.01
            low = min(open_, close) * 0.99
            volume = int(rng.integers(1_000_000, 5_000_000))
            rows.append(
                {
                    "ticker": ticker,
                    "ts": ts.date(),
                    "open": round(open_, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": volume,
                }
            )
            price = close
        frames.append(pd.DataFrame(rows))

    return pd.concat(frames).sort_values(["ticker", "ts"]).reset_index(drop=True)
