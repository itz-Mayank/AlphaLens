import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.sql_helpers import sql_string_list


class JobType:
    MARKET_DATA_INGESTION = "MARKET_DATA_INGESTION"
    NEWS_INGESTION = "NEWS_INGESTION"
    ALERT_EVALUATION = "ALERT_EVALUATION"
    MODEL_RETRAINING = "MODEL_RETRAINING"
    PREDICTION_EVALUATION = "PREDICTION_EVALUATION"
    FUNDAMENTALS_INGESTION = "FUNDAMENTALS_INGESTION"
    MACRO_INGESTION = "MACRO_INGESTION"

    ALL = (
        MARKET_DATA_INGESTION,
        NEWS_INGESTION,
        ALERT_EVALUATION,
        MODEL_RETRAINING,
        PREDICTION_EVALUATION,
        FUNDAMENTALS_INGESTION,
        MACRO_INGESTION,
    )


class JobStatus:
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    ALL = (QUEUED, RUNNING, COMPLETED, FAILED)


class Job(Base):
    """Generic background-job tracking row. Deliberately generic (not
    `IngestionJob`) so later phases (training, backtests, news processing,
    reports) reuse this table instead of each growing their own — see
    docs/decisions.md ADR-009. `job_type` and `metadata` carry the
    type-specific shape.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(f"job_type IN {sql_string_list(JobType.ALL)}", name="ck_jobs_job_type"),
        CheckConstraint(f"status IN {sql_string_list(JobStatus.ALL)}", name="ck_jobs_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=JobStatus.QUEUED)
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
