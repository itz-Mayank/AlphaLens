"""Fundamentals — as-filed company facts (Phase 10). Deliberately a
structured table, not a JSONB blob, because AlphaLens needs to query by
concept/period with real numeric/date types (Phase 10's explicit
requirement) — never mixed into `PriceBar`, which is a different kind of
fact (a market observation, not a filed one) with different provenance
and freshness semantics entirely.

`security_id` + `concept` + `unit` + `period_end` + `fiscal_period` +
`form` is this table's natural identity — re-ingesting the same filing
updates the same row (idempotent, ON CONFLICT DO UPDATE) rather than
duplicating it.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

# Generous precision/scale — a real company's `Assets` can be in the
# hundreds of billions; `CommonStockSharesOutstanding` is also stored here
# despite being a share count, not a dollar amount, so this must comfortably
# hold both without truncation.
_FACT_VALUE = Numeric(24, 4)


class Fundamental(Base):
    __tablename__ = "fundamentals"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "concept", "unit", "period_end", "fiscal_period", "form",
            name="uq_fundamentals_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    concept: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[Decimal] = mapped_column(_FACT_VALUE, nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    period_start: Mapped[date | None] = mapped_column(nullable=True)
    period_end: Mapped[date] = mapped_column(nullable=False, index=True)
    fiscal_year: Mapped[int | None] = mapped_column(nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(10), nullable=True)
    form: Mapped[str] = mapped_column(String(20), nullable=False)
    filed_date: Mapped[date] = mapped_column(nullable=False)
    accession_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
