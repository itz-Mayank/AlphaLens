import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Watchlist(Base):
    """A user-owned named list of securities. A user may have any number of
    watchlists (no "one default list" assumption) — see docs/decisions.md's
    Phase 9 ADR. Ownership is enforced at the service layer by always
    scoping lookups to the authenticated user's id, never trusting a
    client-supplied id alone (mirrors the research agent's conversation
    isolation pattern from Phase 8)."""

    __tablename__ = "watchlists"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WatchlistItem(Base):
    """One security on one watchlist. Unique on `(watchlist_id,
    security_id)` — adding the same security twice is a no-op, not a
    duplicate row. `ondelete="CASCADE"` on both FKs: deleting a watchlist
    drops its items, and delisting/removing a security (never done today,
    but the constraint should still be correct) drops the item rather than
    leaving a dangling reference."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint(
            "watchlist_id", "security_id", name="uq_watchlist_items_watchlist_security"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("watchlists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
