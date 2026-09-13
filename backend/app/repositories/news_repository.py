"""Repository for `news_articles` / `article_securities` / `news_sentiment`.

Every write here is idempotent by construction (unique-constraint-backed
upserts), matching `PriceBarRepository`'s pattern: re-running ingestion or
re-processing sentiment for the same article never creates a duplicate row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.news import ArticleSecurity, ContentStatus, NewsArticle, NewsSentiment
from app.providers.base import NewsArticleData


@dataclass(frozen=True)
class EntityMatch:
    security_id: int
    match_method: str
    confidence: Decimal


class NewsRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_articles(
        self, *, source: str, articles: list[NewsArticleData], data_source: str
    ) -> list[NewsArticle]:
        """Idempotent on `(source, external_id)`: an already-stored article
        is left untouched (its content/publish time is a fixed historical
        fact once ingested, never rewritten by re-fetching the same
        window). Returns the full set of DB rows for every `external_id`
        in `articles`, whether newly inserted or already present.
        """
        if not articles:
            return []

        rows = [
            {
                "source": source,
                "external_id": a.external_id,
                "title": a.title,
                "summary": a.summary,
                "url": a.url,
                "publisher": a.publisher,
                "published_at": a.published_at,
                "retrieved_at": datetime.now(UTC),
                "language": a.language,
                "content_status": (
                    ContentStatus.SUMMARY_ONLY if a.summary else ContentStatus.TITLE_ONLY
                ),
                "data_source": data_source,
            }
            for a in articles
        ]
        stmt = pg_insert(NewsArticle).values(rows)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[NewsArticle.source, NewsArticle.external_id]
        )
        self.db.execute(stmt)
        self.db.flush()

        external_ids = [a.external_id for a in articles]
        result = self.db.execute(
            select(NewsArticle).where(
                NewsArticle.source == source, NewsArticle.external_id.in_(external_ids)
            )
        )
        return list(result.scalars())

    def get_articles_missing_sentiment(
        self, *, model_version: str, limit: int = 200
    ) -> list[NewsArticle]:
        """Articles with no `NewsSentiment` row for `model_version` yet —
        exactly the set `run_news_ingestion` still needs to score. Never
        re-scores an article that already has a row for this model
        version (idempotent processing)."""
        already_scored = select(NewsSentiment.article_id).where(
            NewsSentiment.model_version == model_version
        )
        stmt = (
            select(NewsArticle)
            .where(NewsArticle.id.not_in(already_scored))
            .order_by(NewsArticle.published_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars())

    def add_entity_matches(self, *, article_id: int, matches: list[EntityMatch]) -> None:
        """Idempotent on `(article_id, security_id)` — a match already
        recorded for this pair is left alone, never duplicated."""
        if not matches:
            return
        rows = [
            {
                "article_id": article_id,
                "security_id": m.security_id,
                "match_method": m.match_method,
                "confidence": m.confidence,
            }
            for m in matches
        ]
        stmt = pg_insert(ArticleSecurity).values(rows)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[ArticleSecurity.article_id, ArticleSecurity.security_id]
        )
        self.db.execute(stmt)

    def upsert_sentiment(
        self,
        *,
        article_id: int,
        model_name: str,
        model_version: str,
        positive_prob: float,
        neutral_prob: float,
        negative_prob: float,
        predicted_label: str,
        processed_at: datetime,
    ) -> None:
        """Idempotent on `(article_id, model_version)`: re-processing the
        same article with the same model version updates the stored row in
        place — this is the mechanism that makes "the same article must
        not create duplicate sentiment records" true even if a caller
        mistakenly processes it twice."""
        stmt = pg_insert(NewsSentiment).values(
            article_id=article_id,
            model_name=model_name,
            model_version=model_version,
            positive_prob=positive_prob,
            neutral_prob=neutral_prob,
            negative_prob=negative_prob,
            predicted_label=predicted_label,
            processed_at=processed_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[NewsSentiment.article_id, NewsSentiment.model_version],
            set_={
                "positive_prob": stmt.excluded.positive_prob,
                "neutral_prob": stmt.excluded.neutral_prob,
                "negative_prob": stmt.excluded.negative_prob,
                "predicted_label": stmt.excluded.predicted_label,
                "processed_at": stmt.excluded.processed_at,
            },
        )
        self.db.execute(stmt)

    def get_articles_for_security(
        self,
        *,
        security_id: int,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsArticle]:
        stmt = (
            select(NewsArticle)
            .join(ArticleSecurity, ArticleSecurity.article_id == NewsArticle.id)
            .where(ArticleSecurity.security_id == security_id)
        )
        if since is not None:
            stmt = stmt.where(NewsArticle.published_at >= since)
        if until is not None:
            stmt = stmt.where(NewsArticle.published_at <= until)
        stmt = stmt.order_by(NewsArticle.published_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars())

    def get_sentiment_by_article_id(
        self, article_ids: list[int], *, model_version: str
    ) -> dict[int, NewsSentiment]:
        if not article_ids:
            return {}
        stmt = select(NewsSentiment).where(
            NewsSentiment.article_id.in_(article_ids),
            NewsSentiment.model_version == model_version,
        )
        return {row.article_id: row for row in self.db.execute(stmt).scalars()}
