from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.fundamental import Fundamental
from app.providers.base import CompanyFactsResult


class FundamentalsRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_facts(
        self, *, security_id: int, result: CompanyFactsResult, source: str, retrieved_at: datetime
    ) -> int:
        """Idempotent: re-ingesting the same filing (identified by
        `uq_fundamentals_identity`) updates the row in place rather than
        duplicating it. Returns the number of facts written."""
        if not result.facts:
            return 0

        rows = [
            {
                "security_id": security_id,
                "concept": fact.concept,
                "value": fact.value,
                "unit": fact.unit,
                "period_start": fact.period_start,
                "period_end": fact.period_end,
                "fiscal_year": fact.fiscal_year,
                "fiscal_period": fact.fiscal_period,
                "form": fact.form,
                "filed_date": fact.filed_date,
                "accession_number": fact.accession_number,
                "source": source,
                "retrieved_at": retrieved_at,
            }
            for fact in result.facts
        ]

        stmt = pg_insert(Fundamental).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                Fundamental.security_id,
                Fundamental.concept,
                Fundamental.unit,
                Fundamental.period_end,
                Fundamental.fiscal_period,
                Fundamental.form,
            ],
            set_={
                "value": stmt.excluded.value,
                "period_start": stmt.excluded.period_start,
                "fiscal_year": stmt.excluded.fiscal_year,
                "filed_date": stmt.excluded.filed_date,
                "accession_number": stmt.excluded.accession_number,
                "source": stmt.excluded.source,
                "retrieved_at": stmt.excluded.retrieved_at,
            },
        )
        self.db.execute(stmt)
        return len(rows)

    def get_latest_by_concept(self, *, security_id: int) -> list[Fundamental]:
        """One row per concept: the most recently filed (by `period_end`,
        then `filed_date`) fact for each — what a caller wants when showing
        "the current fundamentals" for a security, as opposed to the full
        filing history."""
        stmt = (
            select(Fundamental)
            .where(Fundamental.security_id == security_id)
            .order_by(
                Fundamental.concept.asc(),
                Fundamental.period_end.desc(),
                Fundamental.filed_date.desc(),
            )
        )
        rows = list(self.db.execute(stmt).scalars())
        latest_by_concept: dict[str, Fundamental] = {}
        for row in rows:
            latest_by_concept.setdefault(row.concept, row)
        return list(latest_by_concept.values())

    def get_history(self, *, security_id: int, concept: str) -> list[Fundamental]:
        stmt = (
            select(Fundamental)
            .where(Fundamental.security_id == security_id, Fundamental.concept == concept)
            .order_by(Fundamental.period_end.asc())
        )
        return list(self.db.execute(stmt).scalars())
