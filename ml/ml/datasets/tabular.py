"""Flat, one-row-per-(ticker, day) dataset for the baseline and XGBoost
tracks. No sequence structure — each row's features already summarize
trailing history via the rolling/EMA features in `ml/features/`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TabularDataset:
    X: pd.DataFrame
    y_return: pd.Series
    y_class: pd.Series
    tickers: pd.Series
    timestamps: pd.Series
    next_day_return: pd.Series
    """The REAL realized return from this row's day to the next trading
    day — always computed from the full, unsplit series (see
    `add_next_day_return`), so a row at a split boundary still gets the
    correct value rather than an artifact of where the split cut. Used by
    `ml.evaluation.financial.evaluate_strategy` — never derived from
    `y_return` (the `horizon_days`-ahead *forecast target*, a different
    quantity), which is exactly the mistake that would make a financial
    metric describe a strategy nobody could actually run.
    """


NEXT_DAY_RETURN_COLUMN = "next_day_return"


def add_next_day_return(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `NEXT_DAY_RETURN_COLUMN` to `df` (a copy — never mutates the
    input), computed per ticker over the FULL series passed in. Call this
    once, before `ml.datasets.temporal_split.chronological_split`, so
    every split's boundary rows get the true next-day value rather than a
    `NaN` artifact of being that split's last row.

    Uses `.transform()`, not `.groupby().apply()` — see
    `ml.targets.targets.future_return`'s docstring for the exact pandas
    edge case (a single group makes `.apply()` transpose the result
    instead of concatenating it) this sidesteps.
    """
    out = df.copy()
    # pct_change() gives the return *ending* at each row (t-1 -> t);
    # shift(-1) realigns it to "the return starting at this row" (t ->
    # t+1) — both computed within one ticker's rows only, so neither the
    # pct_change baseline nor the shift ever crosses into another
    # ticker's prices.
    out[NEXT_DAY_RETURN_COLUMN] = out.groupby("ticker", sort=False)["close"].transform(
        lambda close: close.pct_change().shift(-1)
    )
    return out


def build_tabular_dataset(
    df: pd.DataFrame,
    *,
    feature_columns: tuple[str, ...],
    return_column: str = "future_return",
    class_column: str = "future_class",
) -> TabularDataset:
    """`df` must already have `NEXT_DAY_RETURN_COLUMN` (via
    `add_next_day_return`, applied before any split). Drops rows with any
    `NaN` among the requested feature/target columns (warm-up rows at the
    start of each ticker's history, and the last `horizon_days` rows of
    each ticker with no known future close — see `ml/targets/targets.py`)
    rather than imputing them. Row order is preserved (still chronological
    per ticker) — callers that need a specific split apply
    `ml.datasets.temporal_split.chronological_split` *before* this
    function, not after, so dropped-row bookkeeping never has to be
    reconciled against split boundaries.
    """
    if NEXT_DAY_RETURN_COLUMN not in df.columns:
        raise ValueError(
            f"df is missing '{NEXT_DAY_RETURN_COLUMN}' — "
            "call add_next_day_return() before splitting"
        )
    required = [*feature_columns, return_column, class_column]
    clean = df.dropna(subset=required).reset_index(drop=True)
    return TabularDataset(
        X=clean[list(feature_columns)].reset_index(drop=True),
        y_return=clean[return_column].reset_index(drop=True),
        y_class=clean[class_column].reset_index(drop=True),
        tickers=clean["ticker"].reset_index(drop=True),
        timestamps=clean["ts"].reset_index(drop=True),
        next_day_return=clean[NEXT_DAY_RETURN_COLUMN].reset_index(drop=True),
    )
