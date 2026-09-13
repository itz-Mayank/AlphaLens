"""Macro economic observations (Phase 10) — independent of any security,
per the explicit requirement not to attach a macro value directly to a
stock row. A feature-engineering layer joins this in later using explicit
temporal semantics (only observations whose `vintage_date` — when the
value was actually known/published — is on or before the prediction
timestamp), never a naive join on `observation_date` alone, which would
leak later-revised figures into a historical feature row.

One row per `(series_id, observation_date)` — re-ingestion overwrites with
the latest known value/vintage (a documented simplification: this does not
retain a full revision history for a metric like GDP that gets restated
multiple times, only the latest known value and the vintage it was known
as of — see docs/decisions.md's Phase 10 provider-ecosystem ADR).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

_OBSERVATION_VALUE = Numeric(20, 6)


class MacroObservation(Base):
    __tablename__ = "macro_observations"
    __table_args__ = (
        UniqueConstraint("series_id", "observation_date", name="uq_macro_observations_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    series_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    observation_date: Mapped[date] = mapped_column(nullable=False, index=True)
    # `None` for a real "no data this period" gap — never a fabricated 0
    # (FRED itself represents this as the literal string "."; see
    # app/providers/macro/fred.py).
    value: Mapped[Decimal | None] = mapped_column(_OBSERVATION_VALUE, nullable=True)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    vintage_date: Mapped[date | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
