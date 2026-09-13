import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.sql_helpers import sql_string_list

_MONEY = Numeric(18, 6)
_QUANTITY = Numeric(20, 8)


class Portfolio(Base):
    """A user-owned portfolio. A user may have any number of portfolios —
    Phase 9 does not assume "one portfolio per user" (see docs/decisions.md
    ADR). `base_currency` is informational only in Phase 9 (every
    transaction is expected to use it; there is no cross-currency
    conversion) — see the accounting ADR's documented limitation.

    Deliberately holds NO derived financial state (no `cash_balance`,
    `total_value`, etc. columns): `Transaction` rows are the sole source of
    truth, and every derived figure (cash, holdings, P&L) is computed by
    `app/services/portfolio_service.py` from the transaction history plus
    current prices — never persisted redundantly, which would risk drifting
    out of sync with the transactions that are the actual ground truth.
    """

    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TransactionType:
    BUY = "BUY"
    SELL = "SELL"
    CASH_DEPOSIT = "CASH_DEPOSIT"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"

    ALL = (BUY, SELL, CASH_DEPOSIT, CASH_WITHDRAWAL)
    SECURITY_TYPES = (BUY, SELL)
    CASH_TYPES = (CASH_DEPOSIT, CASH_WITHDRAWAL)


class Transaction(Base):
    """One immutable financial event on a portfolio — the sole source of
    truth for cash/positions/P&L (see `Portfolio`'s docstring and
    docs/decisions.md's Phase 9 accounting ADR: average-cost basis,
    long-only, fees modeled only on BUY/SELL).

    Two disjoint shapes enforced by `ck_transactions_type_fields`:
      - BUY/SELL: `security_id`, `quantity` (>0), `price` (>=0) are set;
        `amount` is NULL. Cash impact is derived (never stored) as
        `quantity * price ± fees` by the accounting service.
      - CASH_DEPOSIT/CASH_WITHDRAWAL: `amount` (>0) is set; `security_id`,
        `quantity`, `price` are NULL and `fees` is forced to 0 — Phase 9
        does not model transfer fees, only trading fees (a documented
        scope decision, not an oversight).

    `security_id` has no `ondelete` action (defaults to RESTRICT): unlike
    `price_bars`/`watchlist_items`, a transaction is a financial record —
    it must never silently disappear or go stale via a cascaded delete.
    Since nothing in this codebase deletes a `Security` today, this is a
    forward-looking correctness choice, not a currently-exercised path.

    `executed_at` (user-supplied, when the trade/transfer actually
    happened) is kept separate from `created_at` (when the row was
    inserted) specifically so temporal portfolio history
    (`portfolio_service.get_performance_history`) can order and filter by
    the former without ever confusing "when we learned about it" with
    "when it happened" — the same distinction `PriceBar.ts` vs
    `created_at` already draws.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "idempotency_key", name="uq_transactions_portfolio_idempotency_key"
        ),
        CheckConstraint(
            f"transaction_type IN {sql_string_list(TransactionType.ALL)}",
            name="ck_transactions_type",
        ),
        CheckConstraint("fees >= 0", name="ck_transactions_fees_non_negative"),
        CheckConstraint(
            "("
            "transaction_type IN ('BUY', 'SELL') "
            "AND security_id IS NOT NULL "
            "AND quantity IS NOT NULL AND quantity > 0 "
            "AND price IS NOT NULL AND price >= 0 "
            "AND amount IS NULL"
            ") OR ("
            "transaction_type IN ('CASH_DEPOSIT', 'CASH_WITHDRAWAL') "
            "AND security_id IS NULL "
            "AND quantity IS NULL "
            "AND price IS NULL "
            "AND amount IS NOT NULL AND amount > 0 "
            "AND fees = 0"
            ")",
            name="ck_transactions_type_fields",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id"), nullable=True
    )
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(_QUANTITY, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    fees: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    executed_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
