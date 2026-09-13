"""Typed, discriminated-union alert configuration — never arbitrary JSON.
Each alert type has its own Pydantic model with its own validated fields;
`AlertCreate.config`'s `alert_type` field is the discriminator, so an
invalid shape (e.g. `PRICE_ABOVE` missing `threshold`) is a clean 422 at
the API boundary, before it ever reaches the `alerts.config` JSONB column
or `app/services/alert_evaluation_service.py`.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

_INDICATORS = Literal[
    "sma_20", "ema_12", "rsi_14", "macd_line", "macd_signal", "macd_histogram",
    "volatility_20d", "atr_14", "bollinger_percent_b", "relative_volume_20",
]
_FORECAST_CLASSES = Literal["Bearish", "Neutral", "Bullish"]


class PriceAboveConfig(BaseModel):
    alert_type: Literal["PRICE_ABOVE"]
    threshold: float = Field(..., gt=0)


class PriceBelowConfig(BaseModel):
    alert_type: Literal["PRICE_BELOW"]
    threshold: float = Field(..., gt=0)


class PercentChangeAboveConfig(BaseModel):
    alert_type: Literal["PERCENT_CHANGE_ABOVE"]
    threshold_percent: float


class PercentChangeBelowConfig(BaseModel):
    alert_type: Literal["PERCENT_CHANGE_BELOW"]
    threshold_percent: float


class ForecastClassChangeConfig(BaseModel):
    alert_type: Literal["FORECAST_CLASS_CHANGE"]
    watch_class: _FORECAST_CLASSES | None = Field(
        default=None,
        description=(
            "Fire only when the forecast changes TO this class. Omit to fire on any change."
        ),
    )


class SentimentChangeConfig(BaseModel):
    alert_type: Literal["SENTIMENT_CHANGE"]
    threshold_delta: float = Field(..., gt=0, le=2)


class TechnicalThresholdConfig(BaseModel):
    alert_type: Literal["TECHNICAL_THRESHOLD"]
    indicator: _INDICATORS
    operator: Literal["above", "below"]
    threshold: float


AlertConfig = Annotated[
    PriceAboveConfig
    | PriceBelowConfig
    | PercentChangeAboveConfig
    | PercentChangeBelowConfig
    | ForecastClassChangeConfig
    | SentimentChangeConfig
    | TechnicalThresholdConfig,
    Field(discriminator="alert_type"),
]

_AlertConfigAdapter: TypeAdapter[AlertConfig] = TypeAdapter(AlertConfig)


def parse_alert_config(alert_type: str, config: dict) -> BaseModel:
    """Re-validates a stored `Alert.config` dict against its typed shape —
    used by `AlertRead` to echo back a validated config, and available to
    the evaluator/tests as a sanity check that what's in the database still
    matches its declared type."""
    return _AlertConfigAdapter.validate_python({"alert_type": alert_type, **config})


class AlertCreate(BaseModel):
    ticker: str = Field(..., max_length=10)
    config: AlertConfig
    cooldown_minutes: int = Field(default=60, gt=0, le=10_080)  # <= 7 days


class AlertUpdate(BaseModel):
    enabled: bool | None = None
    cooldown_minutes: int | None = Field(default=None, gt=0, le=10_080)


class AlertRead(BaseModel):
    id: uuid.UUID
    ticker: str
    alert_type: str
    config: dict
    enabled: bool
    cooldown_minutes: int
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AlertEventRead(BaseModel):
    id: uuid.UUID
    triggered_at: datetime
    observed_value: dict
    message: str
    created_at: datetime
