"""Serving orchestration: raw OHLCV history -> registered model -> `PredictionResult`.

This is the layer `docs/ml-pipeline.md`/ADR-001 deferred to Phase 6 — Phase 5
built `ml.inference.inference`'s low-level `predict_return`/`predict_direction`
(given an already-loaded model and an already-built feature row) but nothing
that goes from "raw price history" to "which registered model, which feature
row" end to end. This module is still plain `ml/` code — no FastAPI import
here; `backend/app/services/forecast_service.py` is the only thing that
calls into it (ADR-001), and it never trains anything (no `.fit()` call
anywhere in this file).

Feature consistency: `build_latest_feature_row` calls the exact same
`ml.features.pipeline.build_features` training used — never a duplicated or
hand-rolled feature calculation — so a served prediction's features are
computed identically to how the model's training features were computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from ml.data import validation
from ml.features.pipeline import FEATURE_COLUMNS, build_features
from ml.inference.inference import PredictionResult, predict_direction, predict_return
from ml.models.xgboost.model import XGBoostDirectionModel, XGBoostReturnModel
from ml.registry.registry import ModelRegistry
from ml.targets.targets import CLASS_NAMES

# Comfortably covers the longest rolling feature window (`sma_50`) with a
# margin, and matches `SequenceConfig`'s default sequence length so this
# stays a meaningful minimum if a sequence model is ever served too.
MIN_HISTORY_ROWS = 60


class ServingError(Exception):
    """Base class for every controlled serving failure — the backend service
    layer catches this family and maps it to a clean 4xx/5xx response,
    never a raw stack trace (see docs/ml-pipeline.md 'Inference serving')."""


class ModelUnavailableError(ServingError):
    """No registered, evaluated model of the requested type exists yet —
    e.g. a fresh checkout before `ml/scripts/run_real_experiment.py` has
    ever run. A real, expected state, not a bug."""


class UnsupportedTickerError(ServingError):
    """The ticker is not part of the trained model's universe
    (`ExperimentConfig.tickers`) — the model has never been validated on
    it, so this project does not serve a prediction for it rather than
    silently extrapolating out-of-distribution."""

    def __init__(self, message: str, *, ticker: str, supported_tickers: tuple[str, ...]):
        super().__init__(message)
        self.ticker = ticker
        self.supported_tickers = supported_tickers


class InsufficientHistoryError(ServingError):
    def __init__(self, message: str, *, available_rows: int, required_rows: int):
        super().__init__(message)
        self.available_rows = available_rows
        self.required_rows = required_rows


class DataValidationFailedError(ServingError):
    """The supplied price history failed `ml.data.validation.validate` —
    e.g. non-chronological rows, an invalid OHLC relationship. Distinct
    from `InsufficientHistoryError`: this is a data-quality problem, not a
    data-quantity one."""


@dataclass(frozen=True)
class ForecastModels:
    """Both XGBoost models the forecast endpoint combines, plus their full
    registry metadata (needed for provenance fields in the API response)."""

    return_record: dict
    return_model: XGBoostReturnModel
    direction_record: dict
    direction_model: XGBoostDirectionModel

    @property
    def supported_tickers(self) -> tuple[str, ...]:
        return tuple(self.return_record["hyperparameters"]["tickers"])

    @property
    def horizon_days(self) -> int:
        return int(self.return_record["hyperparameters"]["target"]["horizon_days"])

    @property
    def dataset_version(self) -> str:
        return str(self.return_record["dataset_version"])


@dataclass(frozen=True)
class ForecastResult:
    ticker: str
    as_of: date
    horizon_days: int
    dataset_version: str
    return_prediction: PredictionResult
    direction_prediction: PredictionResult


_MODEL_LOADERS = {
    "xgboost_return": XGBoostReturnModel,
    "xgboost_direction": XGBoostDirectionModel,
}


def load_forecast_models(registry_path: Path) -> ForecastModels:
    """Loads the `PRODUCTION`-status `xgboost_return` and `xgboost_direction`
    models from the registry at `registry_path` — never an arbitrary
    filesystem artifact path picked by the caller (`ModelRegistry` is the
    only valid model source; see docs/ml-pipeline.md 'Model selection'),
    and never merely "the best-scoring record regardless of whether it was
    ever approved to serve" (that was a real Phase-9-and-earlier gap: see
    docs/decisions.md's Phase 10 promotion-gate ADR — a model reaches
    `PRODUCTION` only via `ml.registry.promotion.apply_promotion`, which
    requires it to have beaten its baseline and not regressed against
    whatever was previously `PRODUCTION`).

    Raises `ModelUnavailableError` if the registry doesn't exist yet, has
    no `PRODUCTION` model of either required type yet (a real, expected
    state before any training run's candidates have passed the promotion
    gate — never silently falls back to an unpromoted model), the two
    models disagree on feature/dataset version (meaning they were never
    trained together in one coherent experiment), or either artifact's
    on-disk checksum no longer matches what was recorded at promotion time
    (a corrupted or tampered artifact — never loaded and served anyway).
    """
    if not registry_path.exists():
        raise ModelUnavailableError(
            f"No model registry found at {registry_path} — run "
            "ml/scripts/run_real_experiment.py first."
        )
    registry = ModelRegistry(registry_path)

    return_record = registry.get_active("xgboost_return")
    direction_record = registry.get_active("xgboost_direction")
    if return_record is None or direction_record is None:
        missing = "xgboost_return" if return_record is None else "xgboost_direction"
        raise ModelUnavailableError(
            f"No PRODUCTION '{missing}' model is available yet — a candidate must pass "
            "the promotion gate (ml.registry.promotion) before it can be served."
        )
    if return_record["feature_version"] != direction_record["feature_version"]:
        raise ModelUnavailableError(
            "The PRODUCTION return and direction models were trained with different "
            "feature versions — refusing to combine them into one forecast."
        )
    if return_record["dataset_version"] != direction_record["dataset_version"]:
        raise ModelUnavailableError(
            "The PRODUCTION return and direction models were trained on different "
            "dataset versions — refusing to combine them into one forecast."
        )
    for record in (return_record, direction_record):
        if not registry.verify_artifact_integrity(record):
            raise ModelUnavailableError(
                f"Artifact integrity check failed for {record['model_type']!r} "
                f"(record_id={record['record_id']}) — the file(s) at {record['artifact_path']} "
                "no longer match the checksum recorded at registration time."
            )

    return_model = _MODEL_LOADERS["xgboost_return"].load(Path(return_record["artifact_path"]))
    direction_model = _MODEL_LOADERS["xgboost_direction"].load(
        Path(direction_record["artifact_path"])
    )
    return ForecastModels(
        return_record=return_record,
        return_model=return_model,
        direction_record=direction_record,
        direction_model=direction_model,
    )


def build_latest_feature_row(
    ohlcv: pd.DataFrame, *, min_history_rows: int = MIN_HISTORY_ROWS
) -> pd.Series:
    """`ohlcv`: single-ticker history with columns `ticker, ts, open, high,
    low, close, volume`, sorted ascending by `ts`. Returns the fully-warmed
    feature row for the LAST available day — the same `build_features`
    pipeline training used, run on whatever history is supplied, never a
    duplicated calculation.

    Raises `InsufficientHistoryError` if there are fewer than
    `min_history_rows` rows, or if the most recent row's features are still
    `NaN` (warm-up not complete for the longest rolling window). Raises
    `DataValidationFailedError` if the supplied history fails
    `ml.data.validation.validate`.
    """
    if len(ohlcv) < min_history_rows:
        raise InsufficientHistoryError(
            f"Need at least {min_history_rows} trading days of price history, "
            f"got {len(ohlcv)}.",
            available_rows=len(ohlcv),
            required_rows=min_history_rows,
        )

    report = validation.validate(ohlcv, min_history_days=min_history_rows)
    if not report.is_clean:
        raise DataValidationFailedError(f"Price history failed validation:\n{report.summary()}")
    cleaned = validation.clean(ohlcv)

    featured = build_features(cleaned)
    last_row = featured.iloc[-1]
    missing = [c for c in FEATURE_COLUMNS if pd.isna(last_row[c])]
    if missing:
        raise InsufficientHistoryError(
            f"The most recent day's features are not fully warmed up yet: {missing}",
            available_rows=len(ohlcv),
            required_rows=min_history_rows,
        )
    return last_row


def generate_forecast(
    ohlcv: pd.DataFrame, models: ForecastModels, *, ticker: str
) -> ForecastResult:
    """The end-to-end serving path: raw history -> feature row -> both
    XGBoost models -> one combined `ForecastResult`. Never trains anything;
    both models are already-loaded, already-trained artifacts."""
    if ticker not in models.supported_tickers:
        raise UnsupportedTickerError(
            f"'{ticker}' is not in this model's trained universe.",
            ticker=ticker,
            supported_tickers=models.supported_tickers,
        )

    feature_row = build_latest_feature_row(ohlcv)
    as_of = feature_row["ts"]
    X = pd.DataFrame([feature_row[list(FEATURE_COLUMNS)].to_dict()])

    return_prediction = predict_return(
        models.return_model,
        X,
        ticker=ticker,
        as_of=as_of,
        model_name=models.return_record["model_name"],
        model_version=models.return_record["version"],
        feature_set_version=models.return_record["feature_version"],
    )
    direction_prediction = predict_direction(
        models.direction_model,
        X,
        ticker=ticker,
        as_of=as_of,
        model_name=models.direction_record["model_name"],
        model_version=models.direction_record["version"],
        feature_set_version=models.direction_record["feature_version"],
        class_names=CLASS_NAMES,
    )
    return ForecastResult(
        ticker=ticker,
        as_of=as_of,
        horizon_days=models.horizon_days,
        dataset_version=models.dataset_version,
        return_prediction=return_prediction,
        direction_prediction=direction_prediction,
    )


def generate_historical_predictions(ohlcv: pd.DataFrame, models: ForecastModels) -> pd.DataFrame:
    """Batch scoring: one `(ticker, ts)` row per fully-warmed-up day in
    `ohlcv` (potentially many tickers, potentially years of history), each
    with `models.return_model`'s and `models.direction_model`'s
    predictions from that day's own feature row. Powers
    `ml.backtest` (a backtest needs a prediction on every historical day,
    not just the latest one) — the feature pipeline is still the exact
    same `build_features` training and single-day serving both use.

    Every prediction here is computed the same way an equivalent
    `generate_forecast` call on that day's trailing history would have
    been: only trailing-window features, never information from later
    rows — this is a genuine re-application of an already-trained,
    fixed model to historical inputs, not a lookahead-tainted shortcut.
    Restricted to tickers in `models.supported_tickers`; any other ticker
    present in `ohlcv` is silently excluded (this is a batch convenience
    function, not a per-ticker validation gate — a single-ticker/single-day
    call still goes through `generate_forecast`'s explicit
    `UnsupportedTickerError`).
    """
    if ohlcv.empty:
        raise InsufficientHistoryError(
            "No price history was supplied.", available_rows=0, required_rows=1
        )
    universe = ohlcv[ohlcv["ticker"].isin(models.supported_tickers)]
    if universe.empty:
        raise UnsupportedTickerError(
            "None of the supplied tickers are in this model's trained universe.",
            ticker=",".join(sorted(set(ohlcv["ticker"]))),
            supported_tickers=models.supported_tickers,
        )

    report = validation.validate(universe, min_history_days=1)
    if not report.is_clean:
        raise DataValidationFailedError(f"Price history failed validation:\n{report.summary()}")
    cleaned = validation.clean(universe)

    featured = build_features(cleaned)
    usable = featured.dropna(subset=list(FEATURE_COLUMNS)).reset_index(drop=True)
    if usable.empty:
        raise InsufficientHistoryError(
            "No ticker has enough warmed-up history to score even one day.",
            available_rows=len(cleaned),
            required_rows=MIN_HISTORY_ROWS,
        )

    X = usable[list(FEATURE_COLUMNS)]
    expected_returns = models.return_model.predict(X)
    predicted_classes = models.direction_model.predict(X)

    return pd.DataFrame(
        {
            "ticker": usable["ticker"],
            "ts": usable["ts"],
            "price": usable["close"],
            "expected_return": expected_returns,
            "predicted_class": predicted_classes,
        }
    )
