"""phase 10 continuation: fundamentals, macro_observations (provider
ecosystem); jobs.job_type += FUNDAMENTALS_INGESTION, MACRO_INGESTION

Revision ID: 0006_phase10_providers
Revises: 0005_phase10_predictions
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_phase10_providers"
down_revision: str | None = "0005_phase10_predictions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_FACT_VALUE = sa.Numeric(24, 4)
_OBSERVATION_VALUE = sa.Numeric(20, 6)


def upgrade() -> None:
    op.create_table(
        "fundamentals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "security_id", sa.Integer, sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("concept", sa.String(100), nullable=False),
        sa.Column("value", _FACT_VALUE, nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("period_start", sa.Date, nullable=True),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("fiscal_year", sa.Integer, nullable=True),
        sa.Column("fiscal_period", sa.String(10), nullable=True),
        sa.Column("form", sa.String(20), nullable=False),
        sa.Column("filed_date", sa.Date, nullable=False),
        sa.Column("accession_number", sa.String(30), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("retrieved_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "security_id", "concept", "unit", "period_end", "fiscal_period", "form",
            name="uq_fundamentals_identity",
        ),
    )
    op.create_index("ix_fundamentals_security_id", "fundamentals", ["security_id"])
    op.create_index("ix_fundamentals_concept", "fundamentals", ["concept"])
    op.create_index("ix_fundamentals_period_end", "fundamentals", ["period_end"])

    op.create_table(
        "macro_observations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("series_id", sa.String(50), nullable=False),
        sa.Column("observation_date", sa.Date, nullable=False),
        sa.Column("value", _OBSERVATION_VALUE, nullable=True),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column("vintage_date", sa.Date, nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("retrieved_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("series_id", "observation_date", name="uq_macro_observations_identity"),
    )
    op.create_index("ix_macro_observations_series_id", "macro_observations", ["series_id"])
    op.create_index(
        "ix_macro_observations_observation_date", "macro_observations", ["observation_date"]
    )

    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_job_type",
        "jobs",
        "job_type IN ('MARKET_DATA_INGESTION', 'NEWS_INGESTION', 'ALERT_EVALUATION', "
        "'MODEL_RETRAINING', 'PREDICTION_EVALUATION', 'FUNDAMENTALS_INGESTION', "
        "'MACRO_INGESTION')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_job_type",
        "jobs",
        "job_type IN ('MARKET_DATA_INGESTION', 'NEWS_INGESTION', 'ALERT_EVALUATION', "
        "'MODEL_RETRAINING', 'PREDICTION_EVALUATION')",
    )
    op.drop_table("macro_observations")
    op.drop_table("fundamentals")
