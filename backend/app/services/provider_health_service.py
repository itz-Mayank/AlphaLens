"""Provider health/status reporting — GET /api/v1/system/providers.

Reuses the existing generic `jobs` table for "last success"/"last failure"
per provider category rather than adding a new tracking table (no
unnecessary infrastructure — Phase 10 provider-ecosystem requirement).
Never returns a credential, API key, or other sensitive config value —
only which provider is configured, whether it needs a credential, and
whether that credential is present (a boolean, never the value itself).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.job import JobType
from app.repositories.job_repository import JobRepository


@dataclass(frozen=True)
class ProviderStatus:
    category: str
    configured_provider: str
    credential_required: bool
    credential_configured: bool
    last_success_at: str | None
    last_failure_at: str | None
    last_failure_reason: str | None
    last_latency_seconds: float | None


def _job_status(
    jobs: JobRepository, job_type: str
) -> tuple[str | None, str | None, str | None, float | None]:
    completed = jobs.get_latest_completed_by_type(job_type)
    failed = jobs.get_latest_failed_by_type(job_type)

    last_success_at = (
        completed.completed_at.isoformat() if completed and completed.completed_at else None
    )
    last_failure_at = failed.completed_at.isoformat() if failed and failed.completed_at else None
    last_failure_reason = failed.error if failed else None

    latency = None
    if completed is not None and completed.started_at and completed.completed_at:
        latency = (completed.completed_at - completed.started_at).total_seconds()

    return last_success_at, last_failure_at, last_failure_reason, latency


def get_provider_statuses(db: Session) -> list[ProviderStatus]:
    settings = get_settings()
    jobs = JobRepository(db)

    # `credential_required` reflects each concrete provider's real auth
    # model, not a blanket "not demo" guess — SEC EDGAR needs only an
    # identifying User-Agent header (no secret), so it is never reported as
    # requiring a credential the way Twelve Data/FRED's API keys are.
    specs = [
        (
            "market_data",
            settings.market_data_provider,
            JobType.MARKET_DATA_INGESTION,
            settings.market_data_provider.lower() == "twelvedata",
            bool(settings.twelve_data_api_key),
        ),
        (
            "news",
            settings.news_provider,
            JobType.NEWS_INGESTION,
            False,
            True,
        ),
        (
            "fundamentals",
            settings.fundamentals_provider,
            JobType.FUNDAMENTALS_INGESTION,
            False,
            True,
        ),
        (
            "macro",
            settings.macro_provider,
            JobType.MACRO_INGESTION,
            settings.macro_provider.lower() == "fred",
            bool(settings.fred_api_key),
        ),
    ]

    statuses = []
    for category, provider_name, job_type, credential_required, credential_configured in specs:
        last_success_at, last_failure_at, last_failure_reason, latency = _job_status(jobs, job_type)
        statuses.append(
            ProviderStatus(
                category=category,
                configured_provider=provider_name,
                credential_required=credential_required,
                credential_configured=credential_configured if credential_required else True,
                last_success_at=last_success_at,
                last_failure_at=last_failure_at,
                last_failure_reason=last_failure_reason,
                last_latency_seconds=latency,
            )
        )
    return statuses
