"""Deterministic article text processing: whitespace/text normalization and
duplicate detection — never a summarizer, never a content rewriter.

Preserves financial terminology deliberately: no lowercasing, no
punctuation stripping, no digit/currency/percent removal. A financial
sentiment model's signal often lives in exactly those characters
("+15%", "$2.3B", "Q3") — "cleaning" them away would remove the meaning
along with the noise.
"""

from __future__ import annotations

import re

from app.providers.base import NewsArticleData

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Collapses runs of whitespace/newlines/tabs to single spaces and
    strips leading/trailing whitespace. Nothing else — casing, punctuation,
    and numeric/currency symbols are left exactly as the provider supplied
    them."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_article(article: NewsArticleData) -> NewsArticleData:
    """Applies `normalize_text` to `title`/`summary` only — `url`,
    `publisher`, `external_id`, `language` are provider-supplied
    identifiers/metadata, never text-normalized."""
    return NewsArticleData(
        external_id=article.external_id,
        title=normalize_text(article.title),
        summary=normalize_text(article.summary) if article.summary else None,
        url=article.url,
        publisher=article.publisher,
        published_at=article.published_at,
        language=article.language,
    )


def sentiment_input_text(article: NewsArticleData) -> str:
    """The text actually handed to the sentiment model: title + summary
    (when present) — never the bare title alone if a summary exists, since
    a headline alone often carries less tone signal than headline+summary
    together, and never any content beyond what the provider supplied
    (no scraped full body)."""
    if article.summary:
        return f"{article.title}. {article.summary}"
    return article.title


def is_duplicate_content(a: NewsArticleData, b: NewsArticleData) -> bool:
    """True if two articles (typically from different `external_id`s —
    e.g. syndicated wire copy re-published under a different id) carry the
    same normalized title AND the same normalized summary. Case-sensitive
    on purpose: two headlines differing only in casing are vanishingly
    unlikely to be independent, unrelated stories, but this function is
    deliberately conservative rather than fuzzy — a near-miss (one word
    different) is treated as a distinct article, not silently merged.
    """
    if normalize_text(a.title) != normalize_text(b.title):
        return False
    a_summary = normalize_text(a.summary) if a.summary else None
    b_summary = normalize_text(b.summary) if b.summary else None
    return a_summary == b_summary


def deduplicate_articles(articles: list[NewsArticleData]) -> list[NewsArticleData]:
    """Drops later duplicates by normalized title+summary content,
    independent of `external_id` — the `(source, external_id)` DB unique
    constraint already handles exact-identity re-fetches; this catches the
    same story appearing twice under two different ids within one fetch
    batch. Keeps the first (newest, since providers return newest-first)
    occurrence."""
    kept: list[NewsArticleData] = []
    for article in articles:
        if any(is_duplicate_content(article, existing) for existing in kept):
            continue
        kept.append(article)
    return kept


def filter_supported_language(
    articles: list[NewsArticleData], *, supported: tuple[str, ...] = ("en",)
) -> tuple[list[NewsArticleData], list[NewsArticleData]]:
    """`(supported_articles, filtered_out_articles)` — FinBERT is an
    English-only model; a non-English article is not dropped silently
    without a trace, it's returned separately so the caller can record how
    many were filtered and why (mirrors `validate_bars`' issue-reporting
    pattern)."""
    supported_articles = [a for a in articles if a.language in supported]
    filtered_out = [a for a in articles if a.language not in supported]
    return supported_articles, filtered_out
