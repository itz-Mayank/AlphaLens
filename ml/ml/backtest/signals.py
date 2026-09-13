"""Signal generation: model output -> a position weight direction, in
`{-1, 0, +1}`. Long/flat only by default — shorting is never assumed;
`allow_short=True` is an explicit opt-in, not a default (Phase 6 rule: "do
not assume short selling unless explicitly implemented"). Thresholds are
fixed, documented constants here, never tuned against backtest results —
tuning a strategy's own entry rule against the data it's then evaluated on
would be the same test-set leakage `ml.targets.targets`'s classification
thresholds are already careful to avoid at the model level.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalRule:
    bullish_class: str = "Bullish"
    bearish_class: str = "Bearish"
    allow_short: bool = False


DEFAULT_SIGNAL_RULE = SignalRule()


def classification_signal(
    predicted_class: str | None, rule: SignalRule = DEFAULT_SIGNAL_RULE
) -> float:
    """Bullish -> long (`1.0`). Neutral -> flat (`0.0`). Bearish -> flat
    (`0.0`), or short (`-1.0`) only if `rule.allow_short`. `None` (no
    prediction available for this bar) -> flat."""
    if predicted_class is None:
        return 0.0
    if predicted_class == rule.bullish_class:
        return 1.0
    if predicted_class == rule.bearish_class and rule.allow_short:
        return -1.0
    return 0.0


def _is_missing(value: float) -> bool:
    # Local, dependency-light NaN check (avoids importing pandas just for
    # this one-line predicate in a module that otherwise has no need of it).
    return value != value


def return_sign_signal(expected_return: float | None, *, allow_short: bool = False) -> float:
    """For the regression model: long if the forecast is positive, flat (or
    short if `allow_short`) if negative, flat if exactly zero or missing."""
    if expected_return is None or expected_return == 0 or _is_missing(expected_return):
        return 0.0
    if expected_return > 0:
        return 1.0
    return -1.0 if allow_short else 0.0
