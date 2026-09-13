import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.sql_helpers import sql_string_list


class AlertType:
    """Only alert types with deterministic, reliably-computable evaluation
    logic against data AlphaLens actually has — see
    `app/services/alert_evaluation_service.py`. No alert type here requires
    data (e.g. real-time streaming quotes, order-book data) this deployment
    doesn't have."""

    PRICE_ABOVE = "PRICE_ABOVE"
    PRICE_BELOW = "PRICE_BELOW"
    PERCENT_CHANGE_ABOVE = "PERCENT_CHANGE_ABOVE"
    PERCENT_CHANGE_BELOW = "PERCENT_CHANGE_BELOW"
    FORECAST_CLASS_CHANGE = "FORECAST_CLASS_CHANGE"
    SENTIMENT_CHANGE = "SENTIMENT_CHANGE"
    TECHNICAL_THRESHOLD = "TECHNICAL_THRESHOLD"

    ALL = (
        PRICE_ABOVE,
        PRICE_BELOW,
        PERCENT_CHANGE_ABOVE,
        PERCENT_CHANGE_BELOW,
        FORECAST_CLASS_CHANGE,
        SENTIMENT_CHANGE,
        TECHNICAL_THRESHOLD,
    )


class Alert(Base):
    """A user-owned alert condition on one security. `config` is a JSONB
    blob whose shape depends on `alert_type` — never accepted as arbitrary
    unvalidated JSON at the API boundary: `app/schemas/alert.py` defines a
    typed Pydantic model per `alert_type` (a discriminated union) that
    validates the request body before it ever reaches this column, so what
    lands in the database has already been shape-checked once. `enabled`
    lets a user pause an alert without losing its configuration/history.
    `cooldown_minutes` + `last_triggered_at` prevent the same real-world
    condition from re-firing every single evaluation cycle — see
    `alert_evaluation_service.py` for the exact dedup logic."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(f"alert_type IN {sql_string_list(AlertType.ALL)}", name="ck_alerts_type"),
        CheckConstraint("cooldown_minutes > 0", name="ck_alerts_cooldown_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    last_triggered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Evaluator-internal scratch state (e.g. the last-observed forecast
    # class/sentiment label) for CHANGE-detection alert types — distinct
    # from `AlertEvent`, which is only ever a real, user-facing firing.
    # Without remembering the previous value between evaluation cycles, a
    # "did X change" alert type would have no prior value to compare
    # against. `None` until the first evaluation cycle establishes a
    # baseline (which never itself fires an event).
    last_observed_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AlertEvent(Base):
    """One firing of an alert — append-only history, never mutated or
    deleted. `observed_value` records exactly what value tripped the
    condition (e.g. `{"price": 205.10}`) so a user (or the agent) can see
    why it fired without re-deriving it. Evaluation-time cooldown checking
    (not a DB constraint) is what actually prevents duplicate events for
    the same real-world trigger — see `alert_evaluation_service.py`."""

    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    observed_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
