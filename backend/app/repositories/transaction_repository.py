import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.portfolio import Transaction


class TransactionRepository:
    """`portfolio_id` here is always one the caller (the service layer)
    has already verified belongs to the requesting user via
    `PortfolioRepository.get_for_user` — this repository itself does not
    re-check ownership, the same layering `PriceBarRepository` has with
    `SecurityRepository`."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        portfolio_id: uuid.UUID,
        security_id: int | None,
        transaction_type: str,
        quantity: Decimal | None,
        price: Decimal | None,
        amount: Decimal | None,
        fees: Decimal,
        currency: str,
        executed_at: datetime,
        idempotency_key: str | None,
    ) -> Transaction:
        transaction = Transaction(
            portfolio_id=portfolio_id,
            security_id=security_id,
            transaction_type=transaction_type,
            quantity=quantity,
            price=price,
            amount=amount,
            fees=fees,
            currency=currency,
            executed_at=executed_at,
            idempotency_key=idempotency_key,
        )
        self.db.add(transaction)
        self.db.flush()
        return transaction

    def get_by_idempotency_key(
        self, *, portfolio_id: uuid.UUID, idempotency_key: str
    ) -> Transaction | None:
        stmt = select(Transaction).where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.idempotency_key == idempotency_key,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_chronological(
        self, *, portfolio_id: uuid.UUID, as_of: datetime | None = None
    ) -> list[Transaction]:
        """Every transaction up to (and including) `as_of`, in a fully
        deterministic order: `executed_at` first (the actual accounting
        order), then `created_at`/`id` as tie-breakers for transactions
        recorded with the same `executed_at`. This ordering is what makes
        average-cost accounting and temporal portfolio history
        reproducible — see `app/services/portfolio_service.py`.
        """
        stmt = select(Transaction).where(Transaction.portfolio_id == portfolio_id)
        if as_of is not None:
            stmt = stmt.where(Transaction.executed_at <= as_of)
        stmt = stmt.order_by(
            Transaction.executed_at.asc(), Transaction.created_at.asc(), Transaction.id.asc()
        )
        return list(self.db.execute(stmt).scalars())

    def list_page(
        self, *, portfolio_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Transaction], int]:
        """Most-recent-first page for display — never used for accounting
        math, which always needs `list_chronological`'s full, ordered,
        unpaginated history."""
        count_stmt = select(func.count()).select_from(Transaction).where(
            Transaction.portfolio_id == portfolio_id
        )
        total = self.db.execute(count_stmt).scalar_one()

        stmt = (
            select(Transaction)
            .where(Transaction.portfolio_id == portfolio_id)
            .order_by(
                Transaction.executed_at.desc(), Transaction.created_at.desc(), Transaction.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars()), total
