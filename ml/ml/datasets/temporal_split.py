"""Chronological train/validation/test splitting. No shuffling anywhere in
this module — `sklearn.model_selection.train_test_split` (or anything
equivalent) is never imported here or anywhere else in this package for
the primary evaluation path. Every split boundary is a calendar date,
applied identically across every ticker (the same three date ranges for
AAPL as for FB), which is what makes "the validation period" and "the test
period" meaningful, comparable, single time windows rather than a
different window per ticker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from ml.config import SplitConfig


@dataclass(frozen=True)
class TemporalSplitBounds:
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date


def chronological_split(
    df: pd.DataFrame, split: SplitConfig
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, TemporalSplitBounds]:
    """`df` must have a `ts` column (date or datetime64). Returns
    `(train, validation, test, bounds)`. Boundaries are inclusive on both
    ends; validation starts the day after `train_end`, test starts the day
    after `validation_end` — there is no gap and no overlap between splits
    by construction (not just by convention)."""
    ts = pd.to_datetime(df["ts"])
    train_end = pd.Timestamp(split.train_end)
    validation_end = pd.Timestamp(split.validation_end)

    if train_end >= validation_end:
        raise ValueError(
            f"train_end ({train_end.date()}) must be before validation_end "
            f"({validation_end.date()})"
        )

    train_mask = ts <= train_end
    validation_mask = (ts > train_end) & (ts <= validation_end)
    test_mask = ts > validation_end

    train_df = df.loc[train_mask].reset_index(drop=True)
    validation_df = df.loc[validation_mask].reset_index(drop=True)
    test_df = df.loc[test_mask].reset_index(drop=True)

    if train_df.empty or validation_df.empty or test_df.empty:
        raise ValueError(
            "One or more splits is empty for the given boundaries — "
            f"train={len(train_df)} validation={len(validation_df)} test={len(test_df)} rows"
        )

    bounds = TemporalSplitBounds(
        train_start=ts.min().date(),
        train_end=train_end.date(),
        validation_start=(train_end + pd.Timedelta(days=1)).date(),
        validation_end=validation_end.date(),
        test_start=(validation_end + pd.Timedelta(days=1)).date(),
        test_end=ts.max().date(),
    )
    return train_df, validation_df, test_df, bounds
