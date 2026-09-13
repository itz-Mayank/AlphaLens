from functools import lru_cache

from app.core.config import get_settings
from app.providers.base import MarketDataProvider
from app.providers.market_data.demo import DemoMarketDataProvider
from app.providers.market_data.twelvedata import TwelveDataMarketDataProvider


@lru_cache
def get_market_data_provider() -> MarketDataProvider:
    """Config-driven via `MARKET_DATA_PROVIDER` — never hardcoded, and
    `demo_mode` alone no longer implicitly decides this (Phase 10):
    `MARKET_DATA_PROVIDER` defaults to `"demo"` when `DEMO_MODE=true` and
    must be explicitly set otherwise, so a deployment can never silently
    fall back to demo data by omission."""
    settings = get_settings()
    provider = settings.market_data_provider.lower()

    if provider == "demo":
        return DemoMarketDataProvider()
    if provider == "twelvedata":
        return TwelveDataMarketDataProvider(api_key=settings.twelve_data_api_key)

    raise NotImplementedError(
        f"Unknown MARKET_DATA_PROVIDER={settings.market_data_provider!r}. "
        "Supported values: 'demo', 'twelvedata'."
    )
