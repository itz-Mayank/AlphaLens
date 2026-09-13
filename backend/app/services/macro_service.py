"""Macro domain logic: ingestion orchestration and query. Mirrors
`market_data_service.py`/`fundamentals_service.py`'s split — a plain
function called directly by tests and by the Celery task wrapper.

Macro observations are stored independently of any security (see
app/db/models/macro_observation.py) — this module never joins them to a
`Security` row. A later feature-engineering step is responsible for the
no-look-ahead-bias join via `MacroRepository.get_as_of`, not this module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.providers.base import MacroDataProvider
from app.providers.http_client import ProviderError
from app.providers.macro import get_macro_provider
from app.repositories.job_repository import JobRepository
from app.repositories.macro_repository import MacroRepository

logger = get_logger(__name__)

# A deliberately small, fixed set of series this deployment tracks — "select
# a small useful set of indicators (not dozens)" per the Phase 10
# provider-ecosystem requirement. Extending this list is a product decision,
# not something ingestion should infer on its own.
TRACKED_SERIES = ("FEDFUNDS", "CPIAUCSL", "UNRATE", "GDP", "DGS10")


@dataclass(frozen=True)
class MacroObservationView:
    observation_date: str
    value: str | None
    unit: str
    frequency: str
    vintage_date: str | None


@dataclass(frozen=True)
class MacroSeriesReport:
    series_id: str
    available: bool
    reason: str | None
    source: str | None
    observations: list[MacroObservationView]


def run_ingestion(
    db: Session,
    *,
    job_id: uuid.UUID,
    series_id: str,
    start: date,
    end: date,
    provider: MacroDataProvider | None = None,
) -> None:
    provider = provider or get_macro_provider()
    jobs = JobRepository(db)
    macro = MacroRepository(db)

    job = jobs.get_by_id(job_id)
    if job is None:
        logger.error("macro_ingestion_job_not_found", job_id=str(job_id))
        return

    jobs.mark_running(job)
    db.flush()

    try:
        observations = provider.get_observations(series_id, start=start, end=end)
        written = macro.upsert_observations(
            series_id=series_id,
            observations=observations,
            source=type(provider).__name__,
            retrieved_at=datetime.now(UTC),
        )
        jobs.mark_completed(
            job,
            metadata={"series_id": series_id, "observations_written": written},
        )
    except ProviderError as exc:
        logger.error("macro_ingestion_failed", series_id=series_id, error=str(exc))
        jobs.mark_failed(job, error=str(exc))

    db.flush()


def get_macro_series(db: Session, *, series_id: str) -> MacroSeriesReport:
    rows = MacroRepository(db).get_series(series_id=series_id)
    if not rows:
        return MacroSeriesReport(
            series_id=series_id,
            available=False,
            reason="No observations have been ingested for this series yet.",
            source=None,
            observations=[],
        )

    return MacroSeriesReport(
        series_id=series_id,
        available=True,
        reason=None,
        source=rows[-1].source,
        observations=[
            MacroObservationView(
                observation_date=row.observation_date.isoformat(),
                value=str(row.value) if row.value is not None else None,
                unit=row.unit,
                frequency=row.frequency,
                vintage_date=row.vintage_date.isoformat() if row.vintage_date else None,
            )
            for row in rows
        ],
    )
