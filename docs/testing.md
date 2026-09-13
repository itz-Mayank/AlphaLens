# Testing Strategy

## Status

Test suites are built out alongside each phase, not deferred to a final hardening pass.

## Backend (`backend/tests/`)

Three tiers, all run against a real PostgreSQL (never SQLite/mocked DB — see below):

- **`unit/`** — no DB, no network. Pure functions: password hashing, JWT encode/decode,
  OHLCV validation rules, the demo market-data generator's determinism.
- **`integration/`** — real Postgres, calling service functions directly (bypassing HTTP and,
  for the Celery task test, bypassing the shared test-transaction fixture too — see
  `tests/integration/test_ingestion_task.py`'s docstring for why a worker-process test needs its
  own real connection). This is where idempotency is actually proven: `run_ingestion` is called
  twice with the same window and the row count is asserted unchanged, not merely reasoned about.
- **`api/`** — real Postgres, through `TestClient` and the full FastAPI stack (auth, rate
  limiting, error handling included). RBAC is tested here as an HTTP-level `403`, not just a unit
  test of `require_roles`.

**Why real Postgres, not SQLite:** the schema uses Postgres-specific features load-bearing to
correctness — `UUID`, `JSONB`, `ON CONFLICT DO UPDATE` upserts, `CHECK` constraints enforcing OHLC
relationships at the DB layer. A SQLite-backed test could pass while the real schema rejects the
same data.

**Test DB setup:** `tests/conftest.py` builds schema from `Base.metadata` (fast, portable across
CI/local) rather than running Alembic — `alembic upgrade head` is run as a separate CI step
specifically to catch migration/model drift (see the `sql_string_list()` gotcha in
[database.md](database.md), caught exactly this way). Each test runs inside a DB transaction that
uses `join_transaction_mode="create_savepoint"` so the app's real `get_db` (commit on success,
rollback on exception) behaves identically to production *within* a test, while the whole thing
rolls back at the end for isolation. A naive "just don't commit" fixture would have hidden a real
bug (see `docs/decisions.md`'s development notes) — this project intentionally avoids that
shortcut.

**Fixtures worth knowing about** (`tests/conftest.py`): `client` / `db_session` (share one
session per test), `auth_headers` (registers a `USER`), `make_user_with_role("ANALYST")` (registers
then promotes a role directly in the DB — there's no self-service API for that, by design), an
autouse Redis-flush fixture (the cache isn't scoped by the DB transaction, so it needs its own
per-test cleanup), and an autouse rate-limiter reset (counters are process-global).

## Frontend (`frontend/tests/`, Vitest + Testing Library)

Component/hook/store tests colocated with source (`Component.test.tsx`). Server calls are mocked
at the `features/<domain>/api.ts` boundary (`vi.mock(...)`), not at `fetch` — except
`lib/api-client.test.ts`, which deliberately tests the 401-refresh-retry logic at the `fetch`
level since that's the layer it actually operates at.

## ML (`ml/tests/`)

Scaffolded, empty pending Phase 5 — nothing to test yet.

## Manual end-to-end verification

Beyond automated tests, each phase is verified once against real running processes (not mocks):
a live FastAPI + a live Celery worker consuming from a live Redis broker + a live Postgres,
driven by a throwaway script. Phase 3's exercised register → login → search (empty) → trigger
ingestion → poll job → verify data appears → verify a second identical ingestion doesn't
duplicate rows (checked via a direct DB count, not just the API) → verify RBAC blocks a plain
`USER` → logout → login → verify persistence. Phase 4's extended this with a specific
**cross-endpoint check**: after real ingestion, assert that `GET /dashboard/overview`'s
`change_percent` for a mover and `GET /stocks/{ticker}`'s `change_percent` for that same ticker
on the same day are *exactly* equal — this is what caught ADR-013's bug (below); an automated
test suite where each endpoint's tests only check internal consistency would not have.

## Bugs this process actually caught (kept as worked examples)

- **`sql_string_list()` (Phase 3).** `app/db/models/job.py` had
  `CheckConstraint(f"job_type IN {JobType.ALL}", ...)` where `JobType.ALL =
  ("MARKET_DATA_INGESTION",)` — a one-element tuple. Python reprs a one-element tuple with a
  trailing comma (`('MARKET_DATA_INGESTION',)`), which is invalid SQL. The hand-written Alembic
  migration was correct (no trailing comma), so `alembic upgrade head` in CI would have passed —
  but `Base.metadata.create_all()`, which the test suite uses to build schema, generates DDL from
  the ORM model and hit the bug immediately, failing every test that touched the database. Fixed
  by `app/db/sql_helpers.py::sql_string_list()`.
- **Naive vs. aware `datetime` columns (Phase 4, ADR-014).** Every ORM model declared
  `Mapped[datetime]` with no explicit column type, which SQLAlchemy defaults to a naive
  `DateTime` — while every migration explicitly declared `TIMESTAMP(timezone=True)`. Invisible
  until `dashboard_service.compute_freshness_status` did `now - latest_ts` and got a hard
  `TypeError`, caught immediately by the integration suite. Fixed once, globally, via `Base.
  type_annotation_map` rather than per-column — see ADR-014.
- **Two formulas for the same number (Phase 4, ADR-013).** `market_data_service.py` and
  `dashboard_service.py` each computed "percent change" with a different but algebraically
  equivalent expression. Both passed their own tests (each was internally consistent); only the
  cross-endpoint manual E2E check above caught that they disagreed in Decimal's last few digits.
  Fixed by making one of them the sole canonical implementation.

The pattern across all three: automated tests within one module, and even a full green test
suite, don't catch bugs that only manifest when two things that are supposed to agree are
actually compared — hence the standing practice of a real, running, manual E2E pass with
specific cross-checks at the end of every phase, not just automated tests in isolation.

Target: meaningful coverage per package, enforced as a floor (not maximized for its own sake) —
see the build plan's Phase 13 entry. Current backend coverage: 97% (`pytest --cov=app`), 99
backend tests, 31 frontend tests.
