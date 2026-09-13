from abc import ABC, abstractmethod


class EmailProvider(ABC):
    """Transactional email delivery. Real SMTP/SES/SendGrid providers plug
    in here later without changing callers (same pattern as MarketDataProvider,
    NewsProvider, FundamentalsProvider — see docs/decisions.md ADR-002)."""

    @abstractmethod
    def send(self, *, to: str, subject: str, body: str) -> None: ...
