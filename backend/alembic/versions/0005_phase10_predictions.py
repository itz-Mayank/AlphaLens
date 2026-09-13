"""phase 10: predictions (model-lifecycle prediction logging);
jobs.job_type += MODEL_RETRAINING, PREDICTION_EVALUATION

Revision ID: 0005_phase10_predictions
Revises: 0004_phase9_portfolios
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_phase10_predictions"
down_revision: str | None = "0004_phase9_portfolios"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_RETURN = sa.Numeric(10, 6)


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "security_id", sa.Integer, sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_type", sa.String(50), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("feature_version", sa.String(50), nullable=False),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("horizon_days", sa.Integer, nullable=False),
        sa.Column("predicted_return", _RETURN, nullable=True),
        sa.Column("predicted_class", sa.String(20), nullable=True),
        sa.Column("predicted_probabilities", postgresql.JSONB, nullable=True),
        sa.Column("prediction_timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("realized_return", _RETURN, nullable=True),
        sa.Column("realized_direction", sa.String(10), nullable=True),
        sa.Column("evaluated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_predictions_security_id", "predictions", ["security_id"])
    op.create_index("ix_predictions_model_type", "predictions", ["model_type"])
    op.create_index("ix_predictions_as_of_date", "predictions", ["as_of_date"])
    # The query `evaluate_matured_predictions` runs every cycle: unevaluated
    # predictions only, oldest first — a partial index keeps that scan
    # bounded to the (small, shrinking) unevaluated set rather than a full
    # table scan as `predictions` grows over the life of the deployment.
    op.create_index(
        "ix_predictions_unevaluated",
        "predictions",
        ["as_of_date"],
        postgresql_where=sa.text("evaluated_at IS NULL"),
    )

    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_job_type",
        "jobs",
        "job_type IN ('MARKET_DATA_INGESTION', 'NEWS_INGESTION', 'ALERT_EVALUATION', "
        "'MODEL_RETRAINING', 'PREDICTION_EVALUATION')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_job_type",
        "jobs",
        "job_type IN ('MARKET_DATA_INGESTION', 'NEWS_INGESTION', 'ALERT_EVALUATION')",
    )
    op.drop_table("predictions")
