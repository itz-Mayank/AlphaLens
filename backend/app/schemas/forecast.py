from datetime import date, datetime

from pydantic import BaseModel


class ForecastResponse(BaseModel):
    ticker: str
    model_name: str
    return_model_version: str
    direction_model_version: str
    feature_version: str
    dataset_version: str
    horizon_days: int
    predicted_direction: str
    expected_return: float | None
    probabilities: dict[str, float] | None
    prediction_timestamp: datetime
    data_timestamp: date
    data_source: str
    # `None` only for a registry record written before this field existed
    # (an append-only JSON file whose schema evolves — see
    # ModelRecordRead's identical comment) — never fabricated when
    # genuinely unknown. Surfaces model "freshness": this model's training
    # data ends `training_period_end`, which can be far in the past
    # relative to `prediction_timestamp` even when `data_source` is real —
    # a distinct staleness risk from the demo/real distinction above.
    training_period_start: date | None = None
    training_period_end: date | None = None
    evaluation_period_end: date | None = None
    disclaimer: str = (
        "Research model output — not financial advice. See data_source: a "
        "forecast computed from demo (synthetic) price data has no real "
        "predictive meaning; only forecasts computed from real market data "
        "reflect this model's validated research performance. See "
        "training_period_end: this model was trained on a fixed historical "
        "snapshot, not continuously retrained — a large gap between "
        "training_period_end and prediction_timestamp means the model has "
        "not been validated against current market conditions."
    )


class FeatureContributionRead(BaseModel):
    feature: str
    value: float
    contribution: float
    direction: str


class ForecastExplanationResponse(BaseModel):
    ticker: str
    predicted_direction: str
    model_version: str
    feature_version: str
    as_of: date
    top_direction_factors: list[FeatureContributionRead]
    top_return_factors: list[FeatureContributionRead]
    data_source: str
    methodology_note: str = (
        "SHAP explains the contribution of features to this model's "
        "prediction; it does not establish causality."
    )
