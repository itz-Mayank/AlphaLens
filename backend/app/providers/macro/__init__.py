from functools import lru_cache

from app.core.config import get_settings
from app.providers.base import MacroDataProvider
from app.providers.macro.fred import FREDMacroProvider
from app.providers.macro.none import NoneMacroProvider


@lru_cache
def get_macro_provider() -> MacroDataProvider:
    settings = get_settings()
    provider = settings.macro_provider.lower()

    if provider == "none":
        return NoneMacroProvider()
    if provider == "fred":
        return FREDMacroProvider(api_key=settings.fred_api_key)

    raise NotImplementedError(
        f"Unknown MACRO_PROVIDER={settings.macro_provider!r}. Supported values: 'none', 'fred'."
    )
