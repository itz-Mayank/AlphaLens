"""Target definitions. This is the one place `.shift(-h)` (a *negative*
shift, pulling a future value backward to align with row `t`) is allowed
anywhere in this package — every other shift in `ml/features/` is positive
(pulling the past forward). `tests/unit/test_targets.py` asserts this
directly against the source of `ml/features/*.py`.

Prediction framing (see docs/ml-pipeline.md for the full data contract):
a prediction made using `X_t` (features known at the close of day `t`)
targets the return from `close_t` to `close_{t+h}` — a decision "at the
close of day t," not "at the open of day t" or intraday.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_HORIZON_DAYS = 5

# Label names, in a fixed order used everywhere a class index is needed
# (e.g. XGBoost's integer-encoded classes, evaluation confusion matrices).
CLASS_NAMES = ("Bearish", "Neutral", "Bullish")


def future_return(df: pd.DataFrame, horizon_days: int = DEFAULT_HORIZON_DAYS) -> pd.Series:
    """`close[t+h] / close[t] - 1`, computed per ticker (grouped) so the
    last `horizon_days` rows of one ticker are never filled in from the
    next ticker's early rows. The last `horizon_days` rows of *each*
    ticker have no known future close and come back as `NaN` — dropped by
    dataset builders, never fabricated as `0` (`0` is a real, meaningful
    "flat" outcome; `NaN` means "we don't know yet").

    Uses `.transform()`, not `.groupby().apply()`: `apply()` has a sharp
    pandas edge case where, with exactly *one* group, it transposes a
    per-row Series result into a single-row DataFrame instead of
    concatenating it back as a Series — silently wrong only when there
    happens to be a single ticker. `transform()` always returns a
    same-shape-as-input Series regardless of group count, which is the
    actual guarantee this function needs.
    """
    return df.groupby("ticker", sort=False)["close"].transform(
        lambda close: close.shift(-horizon_days) / close - 1
    )


def derive_classification_thresholds(
    train_returns: pd.Series, *, num_std: float = 0.5
) -> tuple[float, float]:
    """`(bearish_threshold, bullish_threshold)`, derived from the TRAINING
    split's own return distribution only — never from validation or test
    (that would be leakage: choosing decision boundaries using data the
    model is later "evaluated on unseen" is a contradiction). Symmetric
    around the training mean at `+/- num_std` standard deviations — not
    tuned to hit any particular class balance or test-set metric.
    """
    clean = train_returns.dropna()
    mean, std = clean.mean(), clean.std()
    return float(mean - num_std * std), float(mean + num_std * std)


def classify_return(
    returns: pd.Series, *, bearish_threshold: float, bullish_threshold: float
) -> pd.Series:
    """Maps a return series to `CLASS_NAMES` using fixed, pre-chosen
    thresholds (from `derive_classification_thresholds` on training data,
    or `config.TargetConfig`'s documented fallback constants) — applying
    the *same* thresholds to train/validation/test is what makes this
    leakage-free; only where the thresholds come from matters."""
    labels = pd.Series(CLASS_NAMES[1], index=returns.index, dtype="object")
    labels[returns < bearish_threshold] = CLASS_NAMES[0]
    labels[returns > bullish_threshold] = CLASS_NAMES[2]
    labels[returns.isna()] = pd.NA
    return labels
