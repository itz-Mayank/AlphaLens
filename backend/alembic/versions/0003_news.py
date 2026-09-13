"""news: news_articles, article_securities, news_sentiment; jobs.job_type += NEWS_INGESTION

Revision ID: 0003_news
Revises: 0002_market_data
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_news"
down_revision: str | None = "0002_market_data"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _created_at_column() -> sa.Column:
    return sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_job_type", "jobs", "job_type IN ('MARKET_DATA_INGESTION', 'NEWS_INGESTION')"
    )

    op.create_table(
        "news_articles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("content_status", sa.String(20), nullable=False, server_default="SUMMARY_ONLY"),
        sa.Column("data_source", sa.String(20), nullable=False, server_default="demo"),
        _created_at_column(),
        sa.CheckConstraint(
            "data_source IN ('demo', 'external')", name="ck_news_articles_data_source"
        ),
        sa.CheckConstraint(
            "content_status IN ('SUMMARY_ONLY', 'TITLE_ONLY')",
            name="ck_news_articles_content_status",
        ),
    )
    op.create_unique_constraint(
        "uq_news_articles_source_external_id", "news_articles", ["source", "external_id"]
    )
    op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"])

    op.create_table(
        "article_securities",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "article_id",
            sa.BigInteger,
            sa.ForeignKey("news_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "security_id",
            sa.Integer,
            sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("match_method", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        _created_at_column(),
        sa.CheckConstraint(
            "match_method IN ('TICKER_SYMBOL', 'COMPANY_NAME')",
            name="ck_article_securities_match_method",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_article_securities_confidence_range"
        ),
    )
    op.create_unique_constraint(
        "uq_article_securities_article_security",
        "article_securities",
        ["article_id", "security_id"],
    )
    op.create_index("ix_article_securities_security_id", "article_securities", ["security_id"])

    op.create_table(
        "news_sentiment",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "article_id",
            sa.BigInteger,
            sa.ForeignKey("news_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("positive_prob", sa.Numeric(6, 5), nullable=False),
        sa.Column("neutral_prob", sa.Numeric(6, 5), nullable=False),
        sa.Column("negative_prob", sa.Numeric(6, 5), nullable=False),
        sa.Column("predicted_label", sa.String(20), nullable=False),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        _created_at_column(),
        sa.CheckConstraint(
            "predicted_label IN ('positive', 'neutral', 'negative')",
            name="ck_news_sentiment_predicted_label",
        ),
        sa.CheckConstraint(
            "positive_prob >= 0 AND positive_prob <= 1 "
            "AND neutral_prob >= 0 AND neutral_prob <= 1 "
            "AND negative_prob >= 0 AND negative_prob <= 1",
            name="ck_news_sentiment_prob_range",
        ),
    )
    op.create_unique_constraint(
        "uq_news_sentiment_article_model_version",
        "news_sentiment",
        ["article_id", "model_version"],
    )


def downgrade() -> None:
    op.drop_table("news_sentiment")
    op.drop_table("article_securities")
    op.drop_table("news_articles")
    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_job_type", "jobs", "job_type IN ('MARKET_DATA_INGESTION')")
