"""phase 9: watchlists, portfolios/transactions, alerts/alert_events;
jobs.job_type += ALERT_EVALUATION

Revision ID: 0004_phase9_portfolios
Revises: 0003_news
Create Date: 2026-09-11

Note: the revision id is deliberately kept under 32 characters — Alembic's
own `alembic_version.version_num` column is `VARCHAR(32)`, and a longer id
(the first attempt at naming this migration) fails on `upgrade` with
`StringDataRightTruncation` only *after* every DDL statement above has
already run, leaving the schema and the version table out of sync. Found
by actually running this migration against a real Postgres instance, not
by inspection.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_phase9_portfolios"
down_revision: str | None = "0003_news"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_MONEY = sa.Numeric(18, 6)
_QUANTITY = sa.Numeric(20, 8)


def _uuid_pk() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    # --- watchlists ---------------------------------------------------
    op.create_table(
        "watchlists",
        _uuid_pk(),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])

    op.create_table(
        "watchlist_items",
        _uuid_pk(),
        sa.Column(
            "watchlist_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "security_id", sa.Integer, sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_watchlist_items_watchlist_id", "watchlist_items", ["watchlist_id"])
    op.create_unique_constraint(
        "uq_watchlist_items_watchlist_security", "watchlist_items", ["watchlist_id", "security_id"]
    )

    # --- portfolios / transactions -------------------------------------
    op.create_table(
        "portfolios",
        _uuid_pk(),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="USD"),
        *_timestamps(),
    )
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"])

    op.create_table(
        "transactions",
        _uuid_pk(),
        sa.Column(
            "portfolio_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("security_id", sa.Integer, sa.ForeignKey("securities.id"), nullable=True),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("quantity", _QUANTITY, nullable=True),
        sa.Column("price", _MONEY, nullable=True),
        sa.Column("amount", _MONEY, nullable=True),
        sa.Column("fees", _MONEY, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "transaction_type IN ('BUY', 'SELL', 'CASH_DEPOSIT', 'CASH_WITHDRAWAL')",
            name="ck_transactions_type",
        ),
        sa.CheckConstraint("fees >= 0", name="ck_transactions_fees_non_negative"),
        sa.CheckConstraint(
            "("
            "transaction_type IN ('BUY', 'SELL') "
            "AND security_id IS NOT NULL "
            "AND quantity IS NOT NULL AND quantity > 0 "
            "AND price IS NOT NULL AND price >= 0 "
            "AND amount IS NULL"
            ") OR ("
            "transaction_type IN ('CASH_DEPOSIT', 'CASH_WITHDRAWAL') "
            "AND security_id IS NULL "
            "AND quantity IS NULL "
            "AND price IS NULL "
            "AND amount IS NOT NULL AND amount > 0 "
            "AND fees = 0"
            ")",
            name="ck_transactions_type_fields",
        ),
    )
    op.create_index("ix_transactions_portfolio_id", "transactions", ["portfolio_id"])
    op.create_index("ix_transactions_executed_at", "transactions", ["executed_at"])
    op.create_unique_constraint(
        "uq_transactions_portfolio_idempotency_key",
        "transactions",
        ["portfolio_id", "idempotency_key"],
    )

    # --- alerts / alert_events ------------------------------------------
    op.create_table(
        "alerts",
        _uuid_pk(),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "security_id", sa.Integer, sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alert_type", sa.String(30), nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("cooldown_minutes", sa.Integer, nullable=False, server_default="60"),
        sa.Column("last_triggered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_observed_state", postgresql.JSONB, nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "alert_type IN ("
            "'PRICE_ABOVE', 'PRICE_BELOW', 'PERCENT_CHANGE_ABOVE', 'PERCENT_CHANGE_BELOW', "
            "'FORECAST_CLASS_CHANGE', 'SENTIMENT_CHANGE', 'TECHNICAL_THRESHOLD'"
            ")",
            name="ck_alerts_type",
        ),
        sa.CheckConstraint("cooldown_minutes > 0", name="ck_alerts_cooldown_positive"),
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"])

    op.create_table(
        "alert_events",
        _uuid_pk(),
        sa.Column(
            "alert_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("triggered_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("observed_value", postgresql.JSONB, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_alert_events_alert_id", "alert_events", ["alert_id"])
    op.create_index("ix_alert_events_triggered_at", "alert_events", ["triggered_at"])

    # --- jobs.job_type += ALERT_EVALUATION -------------------------------
    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_job_type",
        "jobs",
        "job_type IN ('MARKET_DATA_INGESTION', 'NEWS_INGESTION', 'ALERT_EVALUATION')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_job_type", "jobs", "job_type IN ('MARKET_DATA_INGESTION', 'NEWS_INGESTION')"
    )

    op.drop_table("alert_events")
    op.drop_table("alerts")
    op.drop_table("transactions")
    op.drop_table("portfolios")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
