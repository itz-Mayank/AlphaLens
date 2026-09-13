from functools import lru_cache

from app.core.config import get_settings
from app.providers.base import FundamentalsProvider
from app.providers.fundamentals.none import NoneFundamentalsProvider
from app.providers.fundamentals.sec_edgar import SECEdgarFundamentalsProvider


@lru_cache
def get_fundamentals_provider() -> FundamentalsProvider:
    """Config-driven, never hardcoded — `FUNDAMENTALS_PROVIDER` selects
    which concrete provider this returns. `none` (the default) is a first-
    class, explicit choice, not a placeholder: a deployment that hasn't
    configured fundamentals gets an honest "unavailable" from
    `NoneFundamentalsProvider`, never a crash and never a silent
    fallback to a different provider than the one requested."""
    settings = get_settings()
    provider = settings.fundamentals_provider.lower()

    if provider == "none":
        return NoneFundamentalsProvider()
    if provider == "sec_edgar":
        return SECEdgarFundamentalsProvider(user_agent=settings.sec_edgar_user_agent)

    raise NotImplementedError(
        f"Unknown FUNDAMENTALS_PROVIDER={settings.fundamentals_provider!r}. "
        "Supported values: 'none', 'sec_edgar'."
    )
