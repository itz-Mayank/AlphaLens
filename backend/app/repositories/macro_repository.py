from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.macro_observation import MacroObservation
from app.providers.base import MacroObservationData


class MacroRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_observations(
        self,
        *,
        series_id: str,
        observations: list[MacroObservationData],
        source: str,
        retrieved_at: datetime,
    ) -> int:
        """Idempotent on `(series_id, observation_date)`. A later re-ingest
        overwrites with the latest known value + vintage — a deliberate
        simplification that does not retain a full revision history (see
        app/db/models/macro_observation.py's module docstring)."""
        if not observations:
            return 0

        rows = [
            {
                "series_id": series_id,
                "observation_date": obs.observation_date,
                "value": obs.value,
                "unit": obs.unit,
                "frequency": obs.frequency,
                "vintage_date": obs.vintage_date,
                "source": source,
                "retrieved_at": retrieved_at,
            }
            for obs in observations
        ]

        stmt = pg_insert(MacroObservation).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[MacroObservation.series_id, MacroObservation.observation_date],
            set_={
                "value": stmt.excluded.value,
                "unit": stmt.excluded.unit,
                "frequency": stmt.excluded.frequency,
                "vintage_date": stmt.excluded.vintage_date,
                "source": stmt.excluded.source,
                "retrieved_at": stmt.excluded.retrieved_at,
            },
        )
        self.db.execute(stmt)
        return len(rows)

    def get_series(self, *, series_id: str) -> list[MacroObservation]:
        stmt = (
            select(MacroObservation)
            .where(MacroObservation.series_id == series_id)
            .order_by(MacroObservation.observation_date.asc())
        )
        return list(self.db.execute(stmt).scalars())

    def get_as_of(
        self, *, series_id: str, as_of: "datetime"
    ) -> MacroObservation | None:
        """The latest observation whose `vintage_date` was known on or
        before `as_of` — the no-look-ahead-bias lookup a feature-engineering
        join must use instead of a naive "latest observation_date" query,
        which would leak values that were not actually known yet at the
        prediction timestamp. Falls back to `observation_date` when
        `vintage_date` is unavailable (documented, conservative: treats the
        observation as known no earlier than the date it describes)."""
        as_of_date = as_of.date() if hasattr(as_of, "date") else as_of
        stmt = (
            select(MacroObservation)
            .where(MacroObservation.series_id == series_id)
            .order_by(MacroObservation.observation_date.desc())
        )
        for row in self.db.execute(stmt).scalars():
            known_date = row.vintage_date or row.observation_date
            if known_date <= as_of_date:
                return row
        return None
