import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.watchlist import Watchlist, WatchlistItem


class WatchlistRepository:
    """Every read here is scoped by `user_id` in the query itself (not
    checked afterward) — a watchlist id belonging to another user simply
    doesn't match the `WHERE` clause and comes back `None`/empty, the same
    shape as "doesn't exist". Callers (the service layer) turn that into a
    404, never a 403 — see docs/security.md: existence of another user's
    resource is never confirmed to a non-owner."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, *, user_id: uuid.UUID, name: str, description: str | None) -> Watchlist:
        watchlist = Watchlist(user_id=user_id, name=name, description=description)
        self.db.add(watchlist)
        self.db.flush()
        return watchlist

    def get_for_user(self, *, watchlist_id: uuid.UUID, user_id: uuid.UUID) -> Watchlist | None:
        stmt = select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_user(self, *, user_id: uuid.UUID) -> list[Watchlist]:
        stmt = (
            select(Watchlist)
            .where(Watchlist.user_id == user_id)
            .order_by(Watchlist.created_at.asc(), Watchlist.id.asc())
        )
        return list(self.db.execute(stmt).scalars())

    def delete(self, watchlist: Watchlist) -> None:
        self.db.delete(watchlist)

    def add_item(self, *, watchlist_id: uuid.UUID, security_id: int) -> None:
        """Idempotent: adding an already-present security is a no-op, not
        a duplicate row or an error — the unique constraint on
        `(watchlist_id, security_id)` is the enforcement, `ON CONFLICT DO
        NOTHING` is just how we avoid turning that into an exception."""
        stmt = (
            pg_insert(WatchlistItem)
            .values(watchlist_id=watchlist_id, security_id=security_id)
            .on_conflict_do_nothing(
                index_elements=[WatchlistItem.watchlist_id, WatchlistItem.security_id]
            )
        )
        self.db.execute(stmt)

    def remove_item(self, *, watchlist_id: uuid.UUID, security_id: int) -> None:
        stmt = delete(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist_id, WatchlistItem.security_id == security_id
        )
        self.db.execute(stmt)

    def list_item_security_ids(self, *, watchlist_id: uuid.UUID) -> list[int]:
        stmt = (
            select(WatchlistItem.security_id)
            .where(WatchlistItem.watchlist_id == watchlist_id)
            .order_by(WatchlistItem.created_at.asc())
        )
        return [row[0] for row in self.db.execute(stmt).all()]

    def count_items(self, *, watchlist_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist_id
        )
        return self.db.execute(stmt).scalar_one()
