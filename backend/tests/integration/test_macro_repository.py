from datetime import UTC, date, datetime
from decimal import Decimal

from app.providers.base import MacroObservationData
from app.repositories.macro_repository import MacroRepository


def _obs(observation_date: date, value, vintage_date: date | None = None) -> MacroObservationData:
    return MacroObservationData(
        series_id="FEDFUNDS",
        observation_date=observation_date,
        value=Decimal(str(value)) if value is not None else None,
        unit="Percent",
        frequency="Monthly",
        vintage_date=vintage_date,
    )


def test_upsert_observations_is_idempotent_on_series_and_date(db_session):
    repo = MacroRepository(db_session)
    obs = [_obs(date(2024, 1, 1), "5.33")]

    written_first = repo.upsert_observations(
        series_id="FEDFUNDS", observations=obs, source="FREDMacroProvider",
        retrieved_at=datetime.now(UTC),
    )
    written_second = repo.upsert_observations(
        series_id="FEDFUNDS", observations=obs, source="FREDMacroProvider",
        retrieved_at=datetime.now(UTC),
    )

    assert written_first == 1
    assert written_second == 1
    assert len(repo.get_series(series_id="FEDFUNDS")) == 1


def test_a_later_ingest_overwrites_the_value_for_the_same_observation_date(db_session):
    repo = MacroRepository(db_session)
    repo.upsert_observations(
        series_id="FEDFUNDS", observations=[_obs(date(2024, 1, 1), "5.25")],
        source="FREDMacroProvider", retrieved_at=datetime.now(UTC),
    )
    repo.upsert_observations(
        series_id="FEDFUNDS", observations=[_obs(date(2024, 1, 1), "5.33")],
        source="FREDMacroProvider", retrieved_at=datetime.now(UTC),
    )

    [row] = repo.get_series(series_id="FEDFUNDS")
    assert row.value == Decimal("5.33")


def test_missing_value_is_stored_as_null_never_zero(db_session):
    repo = MacroRepository(db_session)
    repo.upsert_observations(
        series_id="FEDFUNDS", observations=[_obs(date(2024, 1, 1), None)],
        source="FREDMacroProvider", retrieved_at=datetime.now(UTC),
    )
    [row] = repo.get_series(series_id="FEDFUNDS")
    assert row.value is None


def test_series_are_independent_of_each_other(db_session):
    repo = MacroRepository(db_session)
    repo.upsert_observations(
        series_id="FEDFUNDS", observations=[_obs(date(2024, 1, 1), "5.33")],
        source="FREDMacroProvider", retrieved_at=datetime.now(UTC),
    )
    assert len(repo.get_series(series_id="FEDFUNDS")) == 1
    assert len(repo.get_series(series_id="CPIAUCSL")) == 0


class TestGetAsOfNoLookAheadBias:
    def test_returns_none_when_nothing_was_known_yet_as_of_that_date(self, db_session):
        repo = MacroRepository(db_session)
        repo.upsert_observations(
            series_id="FEDFUNDS",
            observations=[_obs(date(2024, 3, 1), "5.33", vintage_date=date(2024, 4, 1))],
            source="FREDMacroProvider", retrieved_at=datetime.now(UTC),
        )
        # As of Feb 1st, the March observation (vintage April 1st) was not
        # yet known — a naive "latest observation_date" join would wrongly
        # return it and leak a future value into a historical feature.
        result = repo.get_as_of(series_id="FEDFUNDS", as_of=datetime(2024, 2, 1, tzinfo=UTC))
        assert result is None

    def test_returns_the_observation_once_its_vintage_has_passed(self, db_session):
        repo = MacroRepository(db_session)
        repo.upsert_observations(
            series_id="FEDFUNDS",
            observations=[_obs(date(2024, 3, 1), "5.33", vintage_date=date(2024, 4, 1))],
            source="FREDMacroProvider", retrieved_at=datetime.now(UTC),
        )
        result = repo.get_as_of(series_id="FEDFUNDS", as_of=datetime(2024, 5, 1, tzinfo=UTC))
        assert result is not None
        assert result.value == Decimal("5.33")

    def test_picks_the_most_recent_known_observation_not_just_any_known_one(self, db_session):
        repo = MacroRepository(db_session)
        repo.upsert_observations(
            series_id="FEDFUNDS",
            observations=[
                _obs(date(2024, 1, 1), "5.00", vintage_date=date(2024, 2, 1)),
                _obs(date(2024, 2, 1), "5.25", vintage_date=date(2024, 3, 1)),
            ],
            source="FREDMacroProvider", retrieved_at=datetime.now(UTC),
        )
        result = repo.get_as_of(series_id="FEDFUNDS", as_of=datetime(2024, 12, 1, tzinfo=UTC))
        assert result.observation_date == date(2024, 2, 1)
        assert result.value == Decimal("5.25")
