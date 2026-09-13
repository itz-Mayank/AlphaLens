from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.price_bar import PriceBar
from app.db.models.security import Security
from app.providers.base import OHLCVBar


@dataclass(frozen=True)
class LatestQuoteRow:
    """One row per security: its most recent bar, joined with the security's
    display fields, plus the close of the bar immediately before it (via
    `LAG`) so a return can be computed without a second query per security.
    `prev_close` is `None` when a security has only ever had one bar."""

    security_id: int
    ticker: str
    name: str
    sector: str | None
    ts: datetime
    close: Decimal
    volume: int
    prev_close: Decimal | None


class PriceBarRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_many(self, *, security_id: int, bars: list[OHLCVBar]) -> int:
        """Idempotent: re-ingesting the same (security_id, ts) updates the
        existing row in place rather than creating a duplicate. Returns the
        number of rows written (inserted or updated)."""
        if not bars:
            return 0

        rows = [
            {
                "security_id": security_id,
                "ts": datetime.combine(bar.ts, datetime.min.time(), tzinfo=UTC),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adjusted_close": bar.adjusted_close,
                "volume": bar.volume,
            }
            for bar in bars
        ]

        stmt = pg_insert(PriceBar).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PriceBar.security_id, PriceBar.ts],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "adjusted_close": stmt.excluded.adjusted_close,
                "volume": stmt.excluded.volume,
            },
        )
        self.db.execute(stmt)
        return len(rows)

    def get_range(
        self, *, security_id: int, start: datetime | None, end: datetime | None
    ) -> list[PriceBar]:
        stmt = select(PriceBar).where(PriceBar.security_id == security_id)
        if start is not None:
            stmt = stmt.where(PriceBar.ts >= start)
        if end is not None:
            stmt = stmt.where(PriceBar.ts <= end)
        stmt = stmt.order_by(PriceBar.ts.asc())
        return list(self.db.execute(stmt).scalars())

    def get_latest(self, *, security_id: int, limit: int = 2) -> list[PriceBar]:
        stmt = (
            select(PriceBar)
            .where(PriceBar.security_id == security_id)
            .order_by(PriceBar.ts.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars())

    def get_bars_for_securities(
        self, *, security_ids: list[int], start: datetime, end: datetime | None = None
    ) -> list[PriceBar]:
        """Every bar for every security in `security_ids` within
        `[start, end]`, in ONE query — the screener's batched equivalent of
        `get_range` (which is one-security-at-a-time). Callers group the
        result by `security_id` in memory (a handful of securities' worth
        of rows is a trivial in-process grouping, not a database
        round-trip) to compute per-security trailing metrics — see
        `app/services/screener_service.py`. Returns rows ordered by
        `(security_id, ts)` so a caller can group-by without re-sorting.
        """
        if not security_ids:
            return []
        stmt = (
            select(PriceBar)
            .where(PriceBar.security_id.in_(security_ids), PriceBar.ts >= start)
            .order_by(PriceBar.security_id.asc(), PriceBar.ts.asc())
        )
        if end is not None:
            stmt = stmt.where(PriceBar.ts <= end)
        return list(self.db.execute(stmt).scalars())

    def get_latest_quotes(self, *, security_ids: list[int] | None = None) -> list[LatestQuoteRow]:
        """One query, regardless of how many securities: for each security
        with at least one bar, its latest (ticker/name/sector/ts/close/
        volume) plus the close immediately before that bar. Backs both the
        stock list endpoint (previously N+1 — one `get_latest` call per
        row) and the dashboard's movers/breadth/sector aggregation, which
        would be N+1 across the *entire* universe if built the naive way —
        see docs/decisions.md's dashboard ADR.
        """
        prev_close = func.lag(PriceBar.close).over(
            partition_by=PriceBar.security_id, order_by=PriceBar.ts.asc()
        )
        row_number = func.row_number().over(
            partition_by=PriceBar.security_id, order_by=PriceBar.ts.desc()
        )

        windowed = select(
            PriceBar.security_id.label("security_id"),
            PriceBar.ts.label("ts"),
            PriceBar.close.label("close"),
            PriceBar.volume.label("volume"),
            prev_close.label("prev_close"),
            row_number.label("rn"),
        )
        if security_ids is not None:
            windowed = windowed.where(PriceBar.security_id.in_(security_ids))
        windowed_subq = windowed.subquery()

        stmt = (
            select(
                Security.id.label("security_id"),
                Security.ticker,
                Security.name,
                Security.sector,
                windowed_subq.c.ts,
                windowed_subq.c.close,
                windowed_subq.c.volume,
                windowed_subq.c.prev_close,
            )
            .join(windowed_subq, windowed_subq.c.security_id == Security.id)
            .where(windowed_subq.c.rn == 1)
        )

        rows = self.db.execute(stmt).all()
        return [
            LatestQuoteRow(
                security_id=r.security_id,
                ticker=r.ticker,
                name=r.name,
                sector=r.sector,
                ts=r.ts,
                close=r.close,
                volume=r.volume,
                prev_close=r.prev_close,
            )
            for r in rows
        ]
