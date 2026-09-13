"""Prediction records — Phase 10's PREDICTION -> FUTURE OBSERVATION ->
REALIZED OUTCOME -> ERROR/PERFORMANCE pipeline. Every real forecast this
deployment serves (`forecast_service.get_forecast`) is logged here at
serving time with the exact model version/feature version that produced
it. `prediction_service.evaluate_matured_predictions` later fills in
`realized_*`/`evaluated_at` once real price data confirms the horizon has
actually elapsed — never before, and never with a value not backed by a
real `PriceBar`. A prediction whose horizon hasn't elapsed yet
(`evaluated_at IS NULL`) is simply not scoreable yet; it is never treated
as, or defaulted to, a zero-error prediction.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

_RETURN = Numeric(10, 6)


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(50), nullable=False)
    # The feature row's own "as of" date — the last day of price history
    # the prediction was computed from. Horizon maturity is measured from
    # here, not from `created_at` (when the row was inserted).
    as_of_date: Mapped[date] = mapped_column(nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_return: Mapped[Decimal | None] = mapped_column(_RETURN, nullable=True)
    predicted_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    predicted_probabilities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prediction_timestamp: Mapped[datetime] = mapped_column(nullable=False)

    # Filled in only once `as_of_date + horizon_days` (trading days, via
    # real PriceBar rows — never a calendar-day approximation) has
    # actually elapsed. All three are NULL together until then.
    realized_return: Mapped[Decimal | None] = mapped_column(_RETURN, nullable=True)
    realized_direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
