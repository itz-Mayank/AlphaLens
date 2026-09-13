import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PortfolioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    base_currency: str = Field(default="USD", min_length=3, max_length=3)


class PortfolioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    base_currency: str
    created_at: datetime
    updated_at: datetime


_TransactionType = Literal["BUY", "SELL", "CASH_DEPOSIT", "CASH_WITHDRAWAL"]


class TransactionCreate(BaseModel):
    """Mirrors the DB's `ck_transactions_type_fields` CHECK constraint at
    the API boundary, so a shape mismatch is a clean 422 with a specific
    message rather than a raw integrity error surfacing from the service
    layer. `ticker` (not `security_id`) is the request field — resolving it
    is the router's job (`_get_security_or_404`), consistent with every
    other ticker-taking endpoint in this codebase."""

    transaction_type: _TransactionType
    ticker: str | None = Field(default=None, max_length=10)
    quantity: Decimal | None = Field(default=None, gt=0)
    price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = Field(default=None, gt=0)
    fees: Decimal = Field(default=Decimal(0), ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    executed_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_shape(self) -> "TransactionCreate":
        if self.transaction_type in ("BUY", "SELL"):
            if self.ticker is None or self.quantity is None or self.price is None:
                raise ValueError(
                    "BUY/SELL transactions require ticker, quantity, and price."
                )
            if self.amount is not None:
                raise ValueError("BUY/SELL transactions must not set amount.")
        else:
            if self.amount is None:
                raise ValueError("CASH_DEPOSIT/CASH_WITHDRAWAL transactions require amount.")
            if self.ticker is not None or self.quantity is not None or self.price is not None:
                raise ValueError(
                    "CASH_DEPOSIT/CASH_WITHDRAWAL transactions must not set ticker/quantity/price."
                )
            if self.fees != 0:
                raise ValueError("CASH_DEPOSIT/CASH_WITHDRAWAL transactions must not carry fees.")
        return self


class TransactionRead(BaseModel):
    id: uuid.UUID
    transaction_type: str
    ticker: str | None
    quantity: Decimal | None
    price: Decimal | None
    amount: Decimal | None
    fees: Decimal
    currency: str
    executed_at: datetime
    created_at: datetime


class HoldingRead(BaseModel):
    security_id: int
    ticker: str
    name: str
    quantity: Decimal
    average_cost: Decimal
    cost_basis: Decimal
    last_price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_pnl_percent: Decimal | None


class PortfolioAnalyticsResponse(BaseModel):
    cash: Decimal
    invested_capital: Decimal
    total_deposits: Decimal
    total_withdrawals: Decimal
    market_value: Decimal | None
    total_value: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    total_return_percent: Decimal | None
    market_value_is_partial: bool
    holdings: list[HoldingRead]
    methodology_note: str = (
        "Average-cost basis, long-only. total_return_percent is a simple "
        "money-weighted return ((total_value - net_contributed) / "
        "net_contributed), not time-weighted. market_value/total_value are "
        "null (never a fabricated partial sum) whenever any holding's "
        "current price is unavailable — see market_value_is_partial."
    )


class PerformancePointRead(BaseModel):
    as_of: datetime
    cash: Decimal
    market_value: Decimal | None
    total_value: Decimal | None
    net_contributed: Decimal


class PerformanceHistoryResponse(BaseModel):
    available: bool
    reason: str | None
    points: list[PerformancePointRead]
    methodology_note: str = (
        "Each point uses only transactions executed on/before that date and "
        "prices dated on/before that date — never a future transaction or "
        "price. No look-ahead bias."
    )
