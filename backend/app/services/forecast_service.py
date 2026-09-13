"""Forecast + explanation serving. The ONLY backend module that imports
from `ml.inference`/`ml.explainability` (ADR-001) — never `ml.pipelines`,
never any model's `.fit()`. Training never runs here, or anywhere in
`backend/`; this module only ever loads already-trained artifacts from the
registry and calls `.predict()`.

**Data-environment disclosure**: the price history this service feeds into
the model comes from whatever this deployment's `securities`/`price_bars`
tables actually hold — in Demo Mode (the default), that's
`DemoMarketDataProvider`'s synthetic random walk (ADR-007), not the real
historical data the model was trained on
(`ml.data.contracts.RESEARCH_DATASET_VERSION`). A forecast computed from
demo price data is a demonstration of the serving architecture only and
carries no real predictive meaning — every response includes
`data_source` precisely so this is never hidden (see docs/ml-pipeline.md
"Inference serving" and ADR-007's established labeling precedent). This
service never blocks demo-data inference; it discloses it.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
from ml.explainability.shap_explainer import (
    FeatureContribution,
    explain_direction_prediction,
    explain_return_prediction,
)
from ml.features.pipeline import FEATURE_COLUMNS
from ml.inference import serving
from ml.inference.inference import predict_direction, predict_return
from ml.targets.targets import CLASS_NAMES
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models.security import Security
from app.repositories.security_repository import SecurityRepository
from app.services import ml_common, prediction_service
from app.services.market_data_service import fetch_ohlcv_dataframe


def _prepare(db: Session, ticker: str) -> tuple[Security, serving.ForecastModels, pd.Series]:
    """Shared setup for both the forecast and explanation endpoints: look
    up the security, load the registered models, fetch its price history,
    and build the latest feature row. Raises `NotFoundError` for a ticker
    unknown to this deployment's own `securities` table (a plain 404,
    consistent with every other `/stocks/{ticker}` route), or one of the
    `AppError` subclasses above for every `ml.inference.serving.ServingError`
    — never a raw stack trace.
    """
    security = SecurityRepository(db).get_by_ticker(ticker)
    if security is None:
        raise NotFoundError(f"No stock found for ticker '{ticker}'.", code="STOCK_NOT_FOUND")

    try:
        models = ml_common.load_models()
        history = fetch_ohlcv_dataframe(db, security)
        if security.ticker not in models.supported_tickers:
            raise serving.UnsupportedTickerError(
                f"'{security.ticker}' is not in this model's trained universe.",
                ticker=security.ticker,
                supported_tickers=models.supported_tickers,
            )
        feature_row = serving.build_latest_feature_row(history)
    except serving.ServingError as exc:
        raise ml_common.wrap_serving_error(exc) from exc

    return security, models, feature_row


def get_forecast(db: Session, ticker: str) -> dict:
    security, models, feature_row = _prepare(db, ticker)
    as_of = feature_row["ts"]
    X = pd.DataFrame([feature_row[list(FEATURE_COLUMNS)].to_dict()])

    return_prediction = predict_return(
        models.return_model,
        X,
        ticker=security.ticker,
        as_of=as_of,
        model_name=models.return_record["model_name"],
        model_version=models.return_record["version"],
        feature_set_version=models.return_record["feature_version"],
    )
    direction_prediction = predict_direction(
        models.direction_model,
        X,
        ticker=security.ticker,
        as_of=as_of,
        model_name=models.direction_record["model_name"],
        model_version=models.direction_record["version"],
        feature_set_version=models.direction_record["feature_version"],
        class_names=CLASS_NAMES,
    )
    train_period = models.return_record.get("train_period")
    test_period = models.return_record.get("test_period")
    result = {
        "ticker": security.ticker,
        "model_name": "xgboost",
        "return_model_version": return_prediction.model_version,
        "direction_model_version": direction_prediction.model_version,
        "feature_version": return_prediction.feature_set_version,
        "dataset_version": models.dataset_version,
        "horizon_days": models.horizon_days,
        "predicted_direction": direction_prediction.predicted_class,
        "expected_return": return_prediction.expected_return,
        "probabilities": direction_prediction.class_probabilities,
        "prediction_timestamp": return_prediction.prediction_timestamp,
        "data_timestamp": as_of,
        "data_source": security.data_source,
        "training_period_start": train_period[0] if train_period else None,
        "training_period_end": train_period[1] if train_period else None,
        "evaluation_period_end": test_period[1] if test_period else None,
    }

    # Phase 10 prediction logging (see app/services/prediction_service.py):
    # every real forecast this deployment serves is logged here, once,
    # with the exact model version that produced it — never for a
    # screener row's separate in-memory forecast computation, which would
    # massively over-count how many times a prediction was actually made.
    prediction_service.log_prediction(
        db,
        security_id=security.id,
        model_type="xgboost_return",
        model_version=return_prediction.model_version,
        feature_version=return_prediction.feature_set_version,
        as_of_date=as_of,
        horizon_days=models.horizon_days,
        predicted_return=Decimal(str(return_prediction.expected_return)),
        predicted_class=None,
        predicted_probabilities=None,
        prediction_timestamp=return_prediction.prediction_timestamp,
    )
    prediction_service.log_prediction(
        db,
        security_id=security.id,
        model_type="xgboost_direction",
        model_version=direction_prediction.model_version,
        feature_version=direction_prediction.feature_set_version,
        as_of_date=as_of,
        horizon_days=models.horizon_days,
        predicted_return=None,
        predicted_class=direction_prediction.predicted_class,
        predicted_probabilities=direction_prediction.class_probabilities,
        prediction_timestamp=direction_prediction.prediction_timestamp,
    )

    return result


def get_forecast_explanation(db: Session, ticker: str, *, top_n: int = 5) -> dict:
    security, models, feature_row = _prepare(db, ticker)

    predicted_class = models.direction_model.predict(
        pd.DataFrame([feature_row[list(FEATURE_COLUMNS)].to_dict()])
    )[0]
    predicted_class_index = list(CLASS_NAMES).index(predicted_class)

    direction_factors = explain_direction_prediction(
        models.direction_model,
        feature_row,
        FEATURE_COLUMNS,
        predicted_class_index=predicted_class_index,
        top_n=top_n,
    )
    return_factors = explain_return_prediction(
        models.return_model, feature_row, FEATURE_COLUMNS, top_n=top_n
    )

    def _as_dicts(contributions: list[FeatureContribution]) -> list[dict]:
        return [c.as_dict() for c in contributions]

    return {
        "ticker": security.ticker,
        "predicted_direction": predicted_class,
        "model_version": models.direction_record["version"],
        "feature_version": models.direction_record["feature_version"],
        "as_of": feature_row["ts"],
        "top_direction_factors": _as_dicts(direction_factors),
        "top_return_factors": _as_dicts(return_factors),
        "data_source": security.data_source,
    }
