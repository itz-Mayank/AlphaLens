"""Fundamentals domain logic: ingestion orchestration and provenance-carrying
query. Mirrors `market_data_service.py`'s split (a plain function called
directly by tests and by the Celery task wrapper, no Celery/FastAPI import
here) — see docs/decisions.md ADR-001.

Deliberately does NOT compute any derived metric (P/E, growth rate,
valuation) — only as-filed facts are stored and returned. Deriving a ratio
from two facts is a separate, later, correctly-scoped effort (see Phase 10
provider-ecosystem ADR) so that a first, wrong implementation of "P/E"
never quietly ships as if it were a filed number.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.providers.base import FundamentalsProvider
from app.providers.fundamentals import get_fundamentals_provider
from app.providers.http_client import ProviderError
from app.repositories.fundamentals_repository import FundamentalsRepository
from app.repositories.job_repository import JobRepository
from app.repositories.security_repository import SecurityRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class FundamentalFactView:
    concept: str
    value: str
    unit: str
    period_end: str
    fiscal_period: str | None
    form: str
    filed_date: str
    accession_number: str | None


@dataclass(frozen=True)
class FundamentalsReport:
    ticker: str
    available: bool
    reason: str | None
    source: str | None
    retrieved_at: str | None
    facts: list[FundamentalFactView]


def run_ingestion(
    db: Session, *, job_id: uuid.UUID, ticker: str, provider: FundamentalsProvider | None = None
) -> None:
    provider = provider or get_fundamentals_provider()
    jobs = JobRepository(db)
    securities = SecurityRepository(db)
    fundamentals = FundamentalsRepository(db)

    job = jobs.get_by_id(job_id)
    if job is None:
        logger.error("fundamentals_ingestion_job_not_found", job_id=str(job_id))
        return

    jobs.mark_running(job)
    db.flush()

    security = securities.get_by_ticker(ticker)
    if security is None:
        jobs.mark_failed(job, error=f"Unknown ticker '{ticker.upper()}' — not a tracked security.")
        db.flush()
        return

    try:
        result = provider.get_company_facts(ticker)
        if result is None:
            jobs.mark_completed(
                job, metadata={"ticker": ticker.upper(), "facts_written": 0, "available": False}
            )
            db.flush()
            return

        retrieved_at = result.retrieved_at
        written = fundamentals.upsert_facts(
            security_id=security.id,
            result=result,
            source=type(provider).__name__,
            retrieved_at=retrieved_at,
        )
        jobs.mark_completed(
            job,
            metadata={
                "ticker": ticker.upper(),
                "facts_written": written,
                "available": True,
                "retrieved_at": retrieved_at.isoformat(),
            },
        )
    except ProviderError as exc:
        logger.error("fundamentals_ingestion_failed", ticker=ticker, error=str(exc))
        jobs.mark_failed(job, error=str(exc))

    db.flush()


def get_fundamentals(db: Session, *, ticker: str) -> FundamentalsReport | None:
    """`None` when `ticker` isn't a tracked security at all (a 404 case for
    the caller). Otherwise always returns a report — `available=False` with
    a `reason` when nothing has been ingested yet, never a fabricated
    empty-but-successful-looking result."""
    security = SecurityRepository(db).get_by_ticker(ticker)
    if security is None:
        return None

    rows = FundamentalsRepository(db).get_latest_by_concept(security_id=security.id)
    if not rows:
        return FundamentalsReport(
            ticker=security.ticker,
            available=False,
            reason="No fundamentals have been ingested for this security yet.",
            source=None,
            retrieved_at=None,
            facts=[],
        )

    most_recent_retrieval = max(row.retrieved_at for row in rows)
    return FundamentalsReport(
        ticker=security.ticker,
        available=True,
        reason=None,
        source=rows[0].source,
        retrieved_at=most_recent_retrieval.astimezone(UTC).isoformat(),
        facts=[
            FundamentalFactView(
                concept=row.concept,
                value=str(row.value),
                unit=row.unit,
                period_end=row.period_end.isoformat(),
                fiscal_period=row.fiscal_period,
                form=row.form,
                filed_date=row.filed_date.isoformat(),
                accession_number=row.accession_number,
            )
            for row in rows
        ],
    )
