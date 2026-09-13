from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.sql_helpers import sql_string_list


class NewsDataSource:
    """Provenance of an article's data — mirrors `Security.DataSource`
    (ADR-007): demo articles are clearly-labeled synthetic fixtures, never
    presented as real news. See `app/providers/news/demo.py`."""

    DEMO = "demo"
    EXTERNAL = "external"

    ALL = (DEMO, EXTERNAL)


class ContentStatus:
    """What of the article this row actually stores. Never `FULL_TEXT` in
    this codebase today — see docs/decisions.md's news-licensing ADR for
    why only a provider-supplied summary/description is persisted, never
    scraped or reconstructed full article bodies."""

    SUMMARY_ONLY = "SUMMARY_ONLY"
    TITLE_ONLY = "TITLE_ONLY"

    ALL = (SUMMARY_ONLY, TITLE_ONLY)


class EntityMatchMethod:
    """How `ArticleSecurity.security_id` was derived — see
    `app/services/entity_extraction_service.py`."""

    TICKER_SYMBOL = "TICKER_SYMBOL"
    COMPANY_NAME = "COMPANY_NAME"

    ALL = (TICKER_SYMBOL, COMPANY_NAME)


class SentimentLabel:
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"

    ALL = (POSITIVE, NEUTRAL, NEGATIVE)


class NewsArticle(Base):
    """One article, deduplicated on `(source, external_id)` — re-fetching
    the same provider window is idempotent by construction (upsert, not
    append; see `NewsRepository.upsert_many`). Deliberately does not store
    full article body text: `content_status` records that only the
    provider's own title/summary is persisted, never a scraped or
    reconstructed full text (licensing — see docs/decisions.md).
    """

    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_news_articles_source_external_id"),
        CheckConstraint(
            f"data_source IN {sql_string_list(NewsDataSource.ALL)}",
            name="ck_news_articles_data_source",
        ),
        CheckConstraint(
            f"content_status IN {sql_string_list(ContentStatus.ALL)}",
            name="ck_news_articles_content_status",
        ),
        Index("ix_news_articles_published_at", "published_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False)
    published_at: Mapped[datetime] = mapped_column(nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    content_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ContentStatus.SUMMARY_ONLY
    )
    data_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NewsDataSource.DEMO
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class ArticleSecurity(Base):
    """Entity/ticker mapping: which canonical `Security` an article is
    about, and how confident that mapping is. Never a guess presented as
    certain — `confidence` and `match_method` are always recorded, and
    `app/services/entity_extraction_service.py` never creates a row below
    its own minimum-confidence threshold (no invented tickers)."""

    __tablename__ = "article_securities"
    __table_args__ = (
        UniqueConstraint(
            "article_id", "security_id", name="uq_article_securities_article_security"
        ),
        CheckConstraint(
            f"match_method IN {sql_string_list(EntityMatchMethod.ALL)}",
            name="ck_article_securities_match_method",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_article_securities_confidence_range"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    match_method: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class NewsSentiment(Base):
    """One sentiment analysis result for one article, from one model
    version. Unique on `(article_id, model_version)` — the same article
    processed twice by the same model version updates/is skipped rather
    than duplicating (see `NewsRepository.upsert_sentiment`); a future
    model version can coexist alongside older results rather than
    silently overwriting them, since `model_version` is part of the
    identity."""

    __tablename__ = "news_sentiment"
    __table_args__ = (
        UniqueConstraint(
            "article_id", "model_version", name="uq_news_sentiment_article_model_version"
        ),
        CheckConstraint(
            f"predicted_label IN {sql_string_list(SentimentLabel.ALL)}",
            name="ck_news_sentiment_predicted_label",
        ),
        CheckConstraint(
            "positive_prob >= 0 AND positive_prob <= 1 "
            "AND neutral_prob >= 0 AND neutral_prob <= 1 "
            "AND negative_prob >= 0 AND negative_prob <= 1",
            name="ck_news_sentiment_prob_range",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    positive_prob: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    neutral_prob: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    negative_prob: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    predicted_label: Mapped[str] = mapped_column(String(20), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
