from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

_MONEY = Numeric(18, 6)


class PriceBar(Base):
    """One daily OHLCV bar. `ts` is `TIMESTAMPTZ` (not `DATE`) so intraday
    bars are a future addition, not a migration — see ADR-008.

    No separate single-column index on `security_id`: the composite unique
    index below leads with it, so it already serves both "all bars for a
    security" and "date range for a security" query shapes.
    """

    __tablename__ = "price_bars"
    __table_args__ = (
        Index("ix_price_bars_security_id_ts", "security_id", "ts", unique=True),
        CheckConstraint(
            "low <= open AND low <= close AND high >= open AND high >= close AND low <= high",
            name="ck_price_bars_ohlc_relationship",
        ),
        CheckConstraint("volume >= 0", name="ck_price_bars_volume_non_negative"),
        CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0 AND adjusted_close > 0",
            name="ck_price_bars_positive_prices",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(nullable=False)
    open: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    high: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    low: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    close: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    adjusted_close: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
