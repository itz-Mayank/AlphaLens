from app.core.logging import get_logger
from app.providers.email.base import EmailProvider

logger = get_logger(__name__)


class ConsoleEmailProvider(EmailProvider):
    """Demo Mode email delivery: logs the message instead of sending it.

    No SMTP/SES credentials are required to exercise the full forgot-password
    workflow in Demo Mode. Clearly not production email delivery — a real
    provider (SES/SendGrid/SMTP) is a registry addition, not a service change.
    """

    def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info("demo_email_sent", to=to, subject=subject, body=body)
