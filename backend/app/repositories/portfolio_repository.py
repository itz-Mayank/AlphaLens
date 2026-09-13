import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.portfolio import Portfolio


class PortfolioRepository:
    """Ownership-scoped the same way as `WatchlistRepository` — every read
    filters by `user_id` in the query itself, so a non-owner's lookup comes
    back `None`, indistinguishable from "doesn't exist" (see
    docs/security.md)."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self, *, user_id: uuid.UUID, name: str, description: str | None, base_currency: str
    ) -> Portfolio:
        portfolio = Portfolio(
            user_id=user_id, name=name, description=description, base_currency=base_currency
        )
        self.db.add(portfolio)
        self.db.flush()
        return portfolio

    def get_for_user(self, *, portfolio_id: uuid.UUID, user_id: uuid.UUID) -> Portfolio | None:
        stmt = select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_user(self, *, user_id: uuid.UUID) -> list[Portfolio]:
        stmt = (
            select(Portfolio)
            .where(Portfolio.user_id == user_id)
            .order_by(Portfolio.created_at.asc(), Portfolio.id.asc())
        )
        return list(self.db.execute(stmt).scalars())

    def delete(self, portfolio: Portfolio) -> None:
        self.db.delete(portfolio)
