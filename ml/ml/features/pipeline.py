"""Combines every feature module into one deterministic feature frame.

Applied **per ticker** (`groupby("ticker", group_keys=False).apply(...)`) —
every rolling/EMA/diff computation in `ml/features/*.py` must never see
another ticker's rows, otherwise e.g. AAPL's SMA on the first day after a
groupby boundary would include FB's trailing prices. This is the single
most important structural rule in this module; `tests/unit/test_features.py`
verifies it directly by checking that the first `window` rows of every
ticker (except the very first ticker) are still `NaN` for windowed
features, not filled in from the previous ticker's tail.
"""

from __future__ import annotations

import pandas as pd

from ml.features import calendar, momentum, price, trend, volatility, volume

FEATURE_SET_VERSION = "fs_v1"

# The exact, ordered list of feature columns this version produces. Tests
# assert the pipeline's output matches this exactly — a silent column
# add/remove/rename should fail a test, not just quietly change model
# input shape.
FEATURE_COLUMNS: tuple[str, ...] = (
    "return_1d",
    "log_return_1d",
    "return_5d",
    "return_10d",
    "momentum_10d",
    "sma_10",
    "sma_20",
    "sma_50",
    "price_to_sma_20",
    "ema_12",
    "ema_26",
    "price_to_ema_12",
    "rsi_14",
    "macd_line",
    "macd_signal",
    "macd_histogram",
    "roc_10",
    "volatility_10d",
    "volatility_20d",
    "atr_14",
    "bollinger_percent_b",
    "volume_change_1d",
    "rolling_volume_mean_20",
    "relative_volume_20",
    "day_of_week",
    "month",
    "trading_day_position_in_month",
)


def _build_single_ticker_features(group: pd.DataFrame) -> pd.DataFrame:
    close, high, low, vol = group["close"], group["high"], group["low"], group["volume"]
    macd_line, macd_signal, macd_hist = momentum.macd(close)
    upper, middle, lower = volatility.bollinger_bands(close)

    out = pd.DataFrame(index=group.index)
    out["return_1d"] = price.simple_return(close, 1)
    out["log_return_1d"] = price.log_return(close, 1)
    out["return_5d"] = price.rolling_return(close, 5)
    out["return_10d"] = price.rolling_return(close, 10)
    out["momentum_10d"] = price.momentum(close, 10)
    out["sma_10"] = trend.sma(close, 10)
    out["sma_20"] = trend.sma(close, 20)
    out["sma_50"] = trend.sma(close, 50)
    out["price_to_sma_20"] = trend.price_to_sma(close, 20)
    out["ema_12"] = trend.ema(close, 12)
    out["ema_26"] = trend.ema(close, 26)
    out["price_to_ema_12"] = trend.price_to_ema(close, 12)
    out["rsi_14"] = momentum.rsi(close, 14)
    out["macd_line"] = macd_line
    out["macd_signal"] = macd_signal
    out["macd_histogram"] = macd_hist
    out["roc_10"] = momentum.roc(close, 10)
    out["volatility_10d"] = volatility.rolling_volatility(close, 10)
    out["volatility_20d"] = volatility.rolling_volatility(close, 20)
    out["atr_14"] = volatility.atr(high, low, close, 14)
    out["bollinger_percent_b"] = volatility.bollinger_percent_b(close)
    out["volume_change_1d"] = volume.volume_change(vol, 1)
    out["rolling_volume_mean_20"] = volume.rolling_volume_mean(vol, 20)
    out["relative_volume_20"] = volume.relative_volume(vol, 20)
    out["day_of_week"] = calendar.day_of_week(group["ts"])
    out["month"] = calendar.month(group["ts"])
    out["trading_day_position_in_month"] = calendar.trading_day_position_in_month(group["ts"])

    assert list(out.columns) == list(FEATURE_COLUMNS)
    return out


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """`df` must have columns `ticker, ts, open, high, low, close, volume`,
    sorted by `(ticker, ts)` ascending (the contract every
    `ResearchDataProvider` and `ml.data.validation.clean` guarantee).
    Returns `df`'s original columns plus every column in `FEATURE_COLUMNS`,
    same row count and order — rows where a feature's warm-up window
    hasn't been reached yet carry `NaN` there rather than a fabricated
    value, and are dropped later by the dataset builders
    (`ml/datasets/`), not silently zero-filled here.
    """
    feature_frames = []
    for _, group in df.groupby("ticker", sort=False, group_keys=False):
        feature_frames.append(_build_single_ticker_features(group))
    features = pd.concat(feature_frames)
    return pd.concat([df, features.reindex(df.index)], axis=1)
