"""Shared test fixtures.

Schema is built directly from the SQLAlchemy models (Base.metadata) rather
than by running Alembic migrations, so the suite stays fast and portable
across CI/local. `alembic upgrade head` (run separately, e.g. in CI/Docker)
is what dev/prod use and is expected to describe the same schema — see
docs/database.md.

Each test runs inside its own DB transaction that is rolled back afterward,
so tests never leak state into one another and never need manual cleanup.
"""

import pathlib
from collections.abc import Generator

from dotenv import load_dotenv

# Must run before any `app.*` import: those modules call get_settings() at
# import time and cache the result, so env vars need to be in place first.
# pydantic-settings' own env_file loading only covers ".env", not this file.
# override=False so a variable already set in the environment (e.g. CI, or
# a developer pointing at a different local port) wins over the file.
load_dotenv(pathlib.Path(__file__).parent.parent / ".env.test", override=False)

# isort: off
import app.db.models  # noqa: F401  — registers all models on Base.metadata
import pytest
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# isort: on

settings = get_settings()


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """Rate-limit counters are process-global; reset before each test so
    unrelated tests calling the same endpoint repeatedly don't 429 each
    other. Rate limiting itself is covered by a dedicated test."""
    limiter.reset()


@pytest.fixture(autouse=True)
def _flush_redis_cache() -> None:
    """The Redis cache (app/core/cache.py) isn't scoped by the DB
    transaction rollback that isolates everything else — without this, a
    key written by one test would leak into the next and produce a false
    pass/fail (e.g. an "empty list" assertion seeing a previous test's
    cached page). Silently no-ops if Redis isn't reachable, matching the
    cache module's own fail-open behavior."""
    from contextlib import suppress

    from app.core.cache import get_redis_client

    with suppress(Exception):
        get_redis_client().flushdb()


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Generator[Session, None, None]:
    """One session per test, wrapping everything in an outer transaction
    that's rolled back at the end (test isolation) while still letting the
    app's real `get_db` call `session.commit()` per "request" exactly like
    production. `join_transaction_mode="create_savepoint"` makes every
    session-level commit only close a SAVEPOINT (and open the next one),
    never the outer connection-level transaction — so a commit in one
    request is visible to a later request in the same test (e.g. a
    delete-then-read-back sequence across two calls), which a fixture that
    simply skipped commit() would hide instead of exercising.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def register_payload() -> dict:
    return {
        "email": "jane.doe@example.com",
        "password": "correct-horse-9",
        "full_name": "Jane Doe",
    }


@pytest.fixture()
def registered_user(client: TestClient, register_payload: dict) -> dict:
    """Registers a user and returns the parsed AccessTokenResponse body."""
    res = client.post("/api/v1/auth/register", json=register_payload)
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture()
def auth_headers(registered_user: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['access_token']}"}


@pytest.fixture()
def make_user_with_role(client: TestClient, db_session: Session):
    """Registers a distinct user and promotes their role directly in the DB
    (there's no API to self-promote, by design). Authorization is decided
    from the freshly-loaded DB row on every request (see
    app/api/deps.py::get_current_user), not from the role embedded in the
    JWT at issuance, so this take effect on the very next request.
    """
    from app.db.models.user import User

    counter = {"n": 0}

    def _make(role: str) -> dict:
        counter["n"] += 1
        email = f"role-fixture-{counter['n']}@example.com"
        res = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "correct-horse-9", "full_name": "Role Fixture"},
        )
        assert res.status_code == 201, res.text
        body = res.json()

        if role != "USER":
            user = db_session.query(User).filter(User.email == email.lower()).one()
            user.role = role
            db_session.flush()

        return {"Authorization": f"Bearer {body['access_token']}"}

    return _make
