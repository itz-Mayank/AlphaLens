"""market data: securities, price_bars, jobs

Revision ID: 0002_market_data
Revises: 0001_auth_core
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_market_data"
down_revision: str | None = "0001_auth_core"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_MONEY = sa.Numeric(18, 6)


def _created_at_column() -> sa.Column:
    return sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "securities",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("data_source", sa.String(20), nullable=False, server_default="demo"),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        _created_at_column(),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'DELISTED')", name="ck_securities_status"),
        sa.CheckConstraint("data_source IN ('demo', 'external')", name="ck_securities_data_source"),
    )
    op.create_index("ix_securities_ticker", "securities", ["ticker"], unique=True)

    op.create_table(
        "price_bars",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "security_id",
            sa.Integer,
            sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("open", _MONEY, nullable=False),
        sa.Column("high", _MONEY, nullable=False),
        sa.Column("low", _MONEY, nullable=False),
        sa.Column("close", _MONEY, nullable=False),
        sa.Column("adjusted_close", _MONEY, nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False),
        _created_at_column(),
        sa.CheckConstraint(
            "low <= open AND low <= close AND high >= open AND high >= close AND low <= high",
            name="ck_price_bars_ohlc_relationship",
        ),
        sa.CheckConstraint("volume >= 0", name="ck_price_bars_volume_non_negative"),
        sa.CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0 AND adjusted_close > 0",
            name="ck_price_bars_positive_prices",
        ),
    )
    # No separate single-column index on security_id: the composite unique
    # index below leads with security_id, so it already serves both "all
    # bars for a security" and "date range for a security" query shapes —
    # a second index would just be redundant write overhead.
    op.create_index(
        "ix_price_bars_security_id_ts", "price_bars", ["security_id", "ts"], unique=True
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column(
            "security_id",
            sa.Integer,
            sa.ForeignKey("securities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        _created_at_column(),
        sa.CheckConstraint("job_type IN ('MARKET_DATA_INGESTION')", name="ck_jobs_job_type"),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED')", name="ck_jobs_status"
        ),
    )
    op.create_index("ix_jobs_job_type", "jobs", ["job_type"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("price_bars")
    op.drop_table("securities")
