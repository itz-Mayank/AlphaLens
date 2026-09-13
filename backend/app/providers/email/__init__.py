from functools import lru_cache

from app.providers.email.base import EmailProvider
from app.providers.email.console import ConsoleEmailProvider


@lru_cache
def get_email_provider() -> EmailProvider:
    # Demo Mode always uses ConsoleEmailProvider today; a real provider
    # (SES/SendGrid/SMTP) selected by settings.demo_mode lands alongside the
    # Phase 3 provider registry for market data / news.
    return ConsoleEmailProvider()
