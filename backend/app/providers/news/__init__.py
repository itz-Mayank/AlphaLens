from functools import lru_cache

from app.core.config import get_settings
from app.providers.base import NewsProvider
from app.providers.news.demo import DemoNewsProvider


@lru_cache
def get_news_provider() -> NewsProvider:
    """Config-driven via `NEWS_PROVIDER` (Phase 10) — see
    `app.providers.market_data.get_market_data_provider`'s docstring for
    why this no longer reads `demo_mode` directly. No real news vendor is
    wired up yet: Phase 10's provider-ecosystem evaluation looked at
    NewsAPI.org (free tier is explicitly localhost-only and forbids
    commercial use — unusable for a deployed server) and Marketaux
    (a promising, finance-specific candidate, but its Terms of Use could
    not be independently verified in that session — a 403 on the terms
    page — so no adapter was written against unverified licensing terms).
    See docs/decisions.md's Phase 10 provider-ecosystem ADR.
    """
    settings = get_settings()
    provider = settings.news_provider.lower()

    if provider == "demo":
        return DemoNewsProvider()

    raise NotImplementedError(
        f"Unknown NEWS_PROVIDER={settings.news_provider!r}. Supported values: 'demo'."
    )
