"""Practical feature-drift monitoring — deliberately NOT a general
statistical framework: this computes Population Stability Index (PSI) plus
a mean/std shift for a small, fixed set of features that already matter
elsewhere in this codebase (the same technical indicators
`get_technical_indicators`/the screener already surface), comparing a
baseline window against the current window of the SAME security's own
real price history.

A drift signal is a monitoring signal, not a verdict: this module never
claims a model is invalid, never blocks serving, and never mutates
anything — it only reports `metric, baseline_period, current_period,
severity, timestamp` for a human (or the dashboard) to look at. Thresholds
are configurable, not hardcoded to force a particular outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from ml.features.pipeline import build_features

from app.services.market_data_service import fetch_ohlcv_dataframe

# Mirrors the indicator set already exposed by get_technical_indicators —
# no new feature computation, just monitoring ones already computed.
MONITORED_FEATURES = ("rsi_14", "sma_20", "volatility_20d", "relative_volume_20")

# Conventional PSI bands (Population Stability Index is a standard,
# widely-used credit-risk/ML-monitoring metric — not invented here):
# < 0.1 no significant shift, 0.1-0.25 moderate, > 0.25 significant.
PSI_MODERATE_THRESHOLD = 0.1
PSI_SIGNIFICANT_THRESHOLD = 0.25
PSI_BUCKETS = 10


@dataclass(frozen=True)
class DriftReport:
    feature: str
    metric: str  # "psi" or "mean_shift_std_units"
    value: float
    baseline_period: tuple[str, str]
    current_period: tuple[str, str]
    severity: str  # "none" | "moderate" | "significant"
    timestamp: str


def _psi(baseline: np.ndarray, current: np.ndarray, *, buckets: int = PSI_BUCKETS) -> float | None:
    """Population Stability Index between two samples of the same
    feature, using baseline-derived quantile bucket edges (so buckets
    reflect the baseline's own distribution, not an arbitrary fixed
    range). Returns `None` if either sample is too small or degenerate
    (e.g. constant) to bucket meaningfully — never a fabricated number."""
    if len(baseline) < buckets or len(current) < buckets:
        return None
    edges = np.unique(np.quantile(baseline, np.linspace(0, 1, buckets + 1)))
    if len(edges) < 3:  # degenerate (near-constant) baseline distribution
        return None
    baseline_counts, _ = np.histogram(baseline, bins=edges)
    current_counts, _ = np.histogram(current, bins=edges)
    baseline_frac = np.clip(baseline_counts / len(baseline), 1e-6, None)
    current_frac = np.clip(current_counts / len(current), 1e-6, None)
    return float(np.sum((current_frac - baseline_frac) * np.log(current_frac / baseline_frac)))


def _severity(psi_value: float) -> str:
    if psi_value >= PSI_SIGNIFICANT_THRESHOLD:
        return "significant"
    if psi_value >= PSI_MODERATE_THRESHOLD:
        return "moderate"
    return "none"


def compute_drift_report(db, security, *, split_fraction: float = 0.5) -> list[DriftReport]:  # noqa: ANN001
    """Splits `security`'s available feature history into an earlier
    baseline window and a later current window (`split_fraction` of the
    way through, chronologically — never a random split, which would leak
    "current" rows into "baseline" and vice versa) and computes PSI +
    mean-shift for each of `MONITORED_FEATURES`. Returns an empty list
    (never a fabricated report) if there isn't enough history to form two
    meaningful windows."""
    history = fetch_ohlcv_dataframe(db, security, lookback_days=730)
    if len(history) < 120:  # need real warm-up plus enough rows per window
        return []
    featured = build_features(history).dropna(subset=list(MONITORED_FEATURES))
    if len(featured) < 120:
        return []

    split_index = int(len(featured) * split_fraction)
    baseline_df = featured.iloc[:split_index]
    current_df = featured.iloc[split_index:]
    if len(baseline_df) < 30 or len(current_df) < 30:
        return []

    baseline_period = (str(baseline_df["ts"].iloc[0]), str(baseline_df["ts"].iloc[-1]))
    current_period = (str(current_df["ts"].iloc[0]), str(current_df["ts"].iloc[-1]))
    timestamp = datetime.now(UTC).isoformat()

    reports: list[DriftReport] = []
    for feature in MONITORED_FEATURES:
        baseline_values = baseline_df[feature].to_numpy()
        current_values = current_df[feature].to_numpy()

        psi_value = _psi(baseline_values, current_values)
        if psi_value is not None:
            reports.append(
                DriftReport(
                    feature=feature,
                    metric="psi",
                    value=psi_value,
                    baseline_period=baseline_period,
                    current_period=current_period,
                    severity=_severity(psi_value),
                    timestamp=timestamp,
                )
            )

        baseline_std = float(np.std(baseline_values))
        if baseline_std > 0:
            mean_shift = float(
                (np.mean(current_values) - np.mean(baseline_values)) / baseline_std
            )
            reports.append(
                DriftReport(
                    feature=feature,
                    metric="mean_shift_std_units",
                    value=mean_shift,
                    baseline_period=baseline_period,
                    current_period=current_period,
                    # A 2-standard-deviation mean shift is a conventional,
                    # non-arbitrary "notable" threshold for this metric —
                    # same "monitoring signal, not a verdict" caveat.
                    severity="significant" if abs(mean_shift) >= 2.0 else "none",
                    timestamp=timestamp,
                )
            )
    return reports
