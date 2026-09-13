from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.security import Security


class SecurityRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_ticker(self, ticker: str) -> Security | None:
        stmt = select(Security).where(Security.ticker == ticker.upper())
        return self.db.execute(stmt).scalar_one_or_none()

    def get_or_create(
        self,
        *,
        ticker: str,
        name: str,
        exchange: str,
        sector: str | None,
        industry: str | None,
        currency: str,
        data_source: str,
    ) -> Security:
        existing = self.get_by_ticker(ticker)
        if existing is not None:
            return existing
        security = Security(
            ticker=ticker.upper(),
            name=name,
            exchange=exchange,
            sector=sector,
            industry=industry,
            currency=currency,
            data_source=data_source,
        )
        self.db.add(security)
        self.db.flush()
        return security

    def search(
        self, *, query: str | None, sector: str | None, limit: int, offset: int
    ) -> tuple[list[Security], int]:
        stmt = select(Security)
        count_stmt = select(func.count()).select_from(Security)

        if query:
            pattern = f"%{query.strip()}%"
            like_clause = (Security.ticker.ilike(pattern)) | (Security.name.ilike(pattern))
            stmt = stmt.where(like_clause)
            count_stmt = count_stmt.where(like_clause)
        if sector:
            stmt = stmt.where(Security.sector == sector)
            count_stmt = count_stmt.where(Security.sector == sector)

        total = self.db.execute(count_stmt).scalar_one()
        stmt = stmt.order_by(Security.ticker).limit(limit).offset(offset)
        results = list(self.db.execute(stmt).scalars())
        return results, total

    def get_by_ids(self, security_ids: list[int]) -> list[Security]:
        """Batched lookup for a known set of ids — one query, used
        wherever a caller already has a set of `security_id`s (e.g. a
        portfolio's holdings, a watchlist's items) and needs their
        display fields without one query per id."""
        if not security_ids:
            return []
        stmt = select(Security).where(Security.id.in_(security_ids))
        return list(self.db.execute(stmt).scalars())

    def list_matching(self, *, query: str | None, sector: str | None) -> list[Security]:
        """Every security matching the (optional) ticker/name substring and
        sector filters — unpaginated, unlike `search()`. Used by the
        screener, which must compute derived metrics (returns, technical
        indicators) for every candidate before it can filter/sort/paginate
        on them — those aren't SQL columns, so pagination has to happen
        after that in-memory computation, not here (see
        `app/services/screener_service.py`)."""
        stmt = select(Security)
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where((Security.ticker.ilike(pattern)) | (Security.name.ilike(pattern)))
        if sector:
            stmt = stmt.where(Security.sector == sector)
        stmt = stmt.order_by(Security.ticker.asc())
        return list(self.db.execute(stmt).scalars())

    def count_all(self) -> int:
        return self.db.execute(select(func.count()).select_from(Security)).scalar_one()

    def list_all(self) -> list[Security]:
        """Every tracked security — used where a caller genuinely needs the
        whole universe (e.g. `entity_extraction_service` matching article
        text against every known company), not a paginated page of it."""
        return list(self.db.execute(select(Security)).scalars())

    def count_by_sector(self) -> dict[str, int]:
        """Total tracked securities per sector — independent of price data,
        so a sector shows up even if nothing in it has been ingested yet."""
        stmt = select(Security.sector, func.count()).group_by(Security.sector)
        return {(sector or "Unknown"): count for sector, count in self.db.execute(stmt).all()}

    def list_distinct_data_sources(self) -> list[str]:
        stmt = select(Security.data_source).distinct()
        return sorted(row[0] for row in self.db.execute(stmt).all())
