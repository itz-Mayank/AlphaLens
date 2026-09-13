from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    Individual model modules under app/db/models/ import this and register
    themselves on it; alembic/env.py imports app.db.models as a package so
    every model is on Base.metadata before autogenerate runs.
    """

    type_annotation_map = {
        # Every model declares `Mapped[datetime]` with no explicit column
        # type; without this, SQLAlchemy defaults to a naive `DateTime`
        # (no timezone) while every migration explicitly creates
        # `TIMESTAMP(timezone=True)` — a model/migration mismatch that's
        # invisible until something compares a stored value against an
        # aware `datetime.now(UTC)` (found via a real test failure, not
        # inspection: `Base.metadata.create_all()`, which the test suite
        # uses to build schema, actually reflects whatever the model says,
        # so it silently built a *naive* test schema against
        # timezone-aware migrations). Fixed once, here, for every model,
        # rather than passing `DateTime(timezone=True)` at each of the ~16
        # call sites — see docs/decisions.md's Phase 4 ADR.
        datetime: DateTime(timezone=True),
    }
