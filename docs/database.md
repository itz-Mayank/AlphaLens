# Database

## Status

Phase 2 (auth core), Phase 3 (market data), Phase 4 (dashboard aggregation — no new tables), and
Phase 7 (news/sentiment) are implemented: `0001_auth_core` creates `users`, `sessions`,
`password_reset_tokens`, `audit_logs`; `0002_market_data` creates `securities`, `price_bars`,
`jobs`; `0003_news` creates `news_articles`, `article_securities`, `news_sentiment`, and adds
`NEWS_INGESTION` to `jobs.job_type`'s allowed values. Phase 6 (ML serving/backtest) added no new
tables — the model registry and backtest results are file-based, not stored in Postgres.

## Conventions (fixed from the start)

- `id BIGSERIAL PRIMARY KEY`, except `UUID` for `users`/`sessions`/`password_reset_tokens` (avoids
  enumeration) and `BIGSERIAL` for `audit_logs` (high write volume, no enumeration concern).
- `created_at`/`updated_at TIMESTAMPTZ DEFAULT now()` on every table. Every ORM `Mapped[datetime]`
  column is timezone-aware by construction — `app/db/base.py`'s `Base.type_annotation_map` maps
  `datetime` to `DateTime(timezone=True)` globally, so this doesn't need repeating per column (see
  ADR-014; this was a real model/migration mismatch until Phase 4, not a preemptive rule).
- `NUMERIC(18,6)` for all money/return columns — never `FLOAT`/`REAL` (see ADR-003 in
  [decisions.md](decisions.md)).
- `CHECK` constraints over native Postgres `ENUM` types, for easier Alembic evolution. Build the
  `IN (...)` value list with `app/db/sql_helpers.py::sql_string_list()`, never
  `f"... IN {some_tuple}"` — Python's repr of a *one-element* tuple has a trailing comma
  (`('X',)`), which is invalid SQL; this broke `jobs.job_type`'s constraint until caught by the
  test suite building schema from these same models (see ADR-009's table).
- `ON DELETE CASCADE` for owned child rows, `ON DELETE RESTRICT` for referenced reference data.
  Exception: `audit_logs.user_id` uses `ON DELETE SET NULL` so the audit trail outlives the
  account (see ADR-006).
- Migrations via Alembic (`backend/alembic/`); autogenerate requires every model module to be
  imported in `backend/alembic/env.py` (done once, in bulk, via `app/db/models/__init__.py`).

## Phase 2 tables

### `users`

| Column              | Type           | Notes                                          |
|---------------------|----------------|-------------------------------------------------|
| `id`                | `UUID`         | PK                                              |
| `email`             | `VARCHAR(320)` | unique, lowercased before storage               |
| `password_hash`     | `VARCHAR(255)` | argon2 (`passlib`), never plaintext             |
| `full_name`         | `VARCHAR(200)` |                                                  |
| `role`              | `VARCHAR(20)`  | `CHECK role IN ('USER','ANALYST','ADMIN')`      |
| `is_active`         | `BOOLEAN`      | default `true`; deactivated users can't log in  |
| `is_email_verified` | `BOOLEAN`      | default `false`; no verification-email flow yet |
| `created_at`/`updated_at` | `TIMESTAMPTZ` |                                             |

### `sessions` (refresh-token sessions)

One row per issued refresh token; only the SHA-256 hash is stored. Refresh rotates the token:
the old row is `revoked_at`-stamped and a new row created — see ADR-005.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | PK |
| `user_id` | `UUID` | FK → `users.id`, `ON DELETE CASCADE` |
| `refresh_token_hash` | `VARCHAR(64)` | unique, SHA-256 hex |
| `user_agent`, `ip_address` | nullable | captured at issuance, for future session-management UI |
| `expires_at` | `TIMESTAMPTZ` | |
| `revoked_at` | `TIMESTAMPTZ`, nullable | set on rotation, logout, or password change |

### `password_reset_tokens`

Same hash-only-storage pattern as `sessions`. `used_at` prevents replay; expiry is
`PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` (default 30).

### `audit_logs`

Append-only. `action` is one of the `AuditAction` constants in
`app/db/models/audit_log.py` (`REGISTER`, `LOGIN`, `LOGIN_FAILED`, `LOGOUT`, `PASSWORD_CHANGE`,
`PASSWORD_RESET_REQUESTED`, `PASSWORD_RESET_COMPLETED`, `PROFILE_UPDATED`, `ACCOUNT_DELETED`).
`metadata` (JSONB) is empty for most actions today — see ADR-006's consequences for what that
means for post-deletion attribution.

## Phase 3 tables

### `securities`

One row per known ticker (`app/db/models/security.py`). `id` is a plain `BIGSERIAL`-style integer,
not `UUID` — tickers are already public, non-enumeration-sensitive identifiers, and using an int
PK keeps `price_bars` FK joins cheaper at scale.

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER` | PK |
| `ticker` | `VARCHAR(20)` | unique, indexed |
| `name`, `exchange`, `sector`, `industry`, `currency` | text | `sector`/`industry` nullable |
| `status` | `VARCHAR(20)` | `CHECK IN ('ACTIVE','DELISTED')` |
| `data_source` | `VARCHAR(20)` | `CHECK IN ('demo','external')` — see ADR-007 |
| `metadata` | `JSONB`, nullable | reserved for provider-specific extras, unused today |

### `price_bars`

One row per (security, day). `ts` is `TIMESTAMPTZ` (see ADR-008), not `DATE`.

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGINT` | PK — expected high row count |
| `security_id` | `INTEGER` | FK → `securities.id`, `ON DELETE CASCADE` |
| `ts` | `TIMESTAMPTZ` | |
| `open`/`high`/`low`/`close`/`adjusted_close` | `NUMERIC(18,6)` | `CHECK`s enforce `low <= open,close <= high` and all `> 0` |
| `volume` | `BIGINT` | `CHECK volume >= 0` |

**Indexing:** a single composite `UNIQUE (security_id, ts)` index — this is both the idempotency
key ingestion upserts on and the index that serves "all bars for a security" / "date-range for a
security" queries (it leads with `security_id`), so no separate single-column index is added.
Phase 4's `PriceBarRepository.get_latest_quotes()` (one window-function query for "every
security's latest quote," backing both `GET /stocks` and `GET /dashboard/overview` — see ADR-011)
also scans via this same index; no new index was needed for it.

**Time-series scaling note (not implemented):** at real-world scale (thousands of securities ×
years of daily bars, or any intraday granularity), this table would eventually want date-range
partitioning (e.g. by year) or a dedicated time-series store — not needed at Demo Mode's data
volume (≈10 securities × ~2-4 years of daily bars), so deliberately not built ahead of need.

### `jobs`

Generic background-job tracking, not `ingestion_jobs` — see ADR-009.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | PK — referenced externally via `GET /jobs/{id}` |
| `job_type` | `VARCHAR(50)` | `CHECK IN ('MARKET_DATA_INGESTION', 'NEWS_INGESTION')`, grows per phase |
| `status` | `VARCHAR(20)` | `CHECK IN ('QUEUED','RUNNING','COMPLETED','FAILED')` |
| `security_id` | `INTEGER`, nullable | FK → `securities.id`, `ON DELETE SET NULL`; null for "all securities" jobs |
| `requested_by_user_id` | `UUID`, nullable | FK → `users.id`, `ON DELETE SET NULL` |
| `started_at`/`completed_at` | `TIMESTAMPTZ`, nullable | |
| `error` | `TEXT`, nullable | set only on `FAILED` |
| `metadata` | `JSONB`, nullable | type-specific — for `MARKET_DATA_INGESTION`: tickers, date range, unknown tickers, per-ticker fetch/write/reject counts |

## Phase 7 tables (news / sentiment)

### `news_articles`

One row per article, deduplicated on `(source, external_id)` (upsert-on-conflict-do-nothing —
an article's content/publish time never changes once ingested). Deliberately has no full-body-text
column — see ADR-025.

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGINT` | PK |
| `source` | `VARCHAR(50)` | which provider (e.g. `demo_provider`) — part of the dedup key |
| `external_id` | `VARCHAR(200)` | the provider's own article id — part of the dedup key |
| `title` | `VARCHAR(500)` | |
| `summary` | `TEXT`, nullable | provider-supplied summary/description only, never a scraped full body |
| `url`, `publisher` | text | |
| `published_at`, `retrieved_at` | `TIMESTAMPTZ` | |
| `language` | `VARCHAR(10)` | default `en` |
| `content_status` | `VARCHAR(20)` | `CHECK IN ('SUMMARY_ONLY','TITLE_ONLY')` |
| `data_source` | `VARCHAR(20)` | `CHECK IN ('demo','external')` — same disclosure pattern as `securities.data_source`, ADR-007 |

**Indexing:** `UNIQUE (source, external_id)` (the idempotency key) plus a plain index on
`published_at` (every read query filters/orders by it — recent news, sentiment windows).

### `article_securities`

Entity/ticker mapping — which `Security` an article is about, and how it was matched (see
ADR-026). Never invents a mapping: a row only exists when
`entity_extraction_service.extract_entities` found a confident match.

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGINT` | PK |
| `article_id` | `BIGINT` | FK → `news_articles.id`, `ON DELETE CASCADE` |
| `security_id` | `INTEGER` | FK → `securities.id`, `ON DELETE CASCADE` |
| `match_method` | `VARCHAR(20)` | `CHECK IN ('TICKER_SYMBOL','COMPANY_NAME')` |
| `confidence` | `NUMERIC(4,3)` | `CHECK BETWEEN 0 AND 1` |

**Indexing:** `UNIQUE (article_id, security_id)` (idempotent re-matching) plus an index on
`security_id` (every "news for this stock" query filters by it).

### `news_sentiment`

One sentiment result per `(article, model_version)` — re-processing the same article with the
same model version updates the row in place (idempotent); a future model version can coexist
alongside older results rather than overwriting them.

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGINT` | PK |
| `article_id` | `BIGINT` | FK → `news_articles.id`, `ON DELETE CASCADE` |
| `model_name`, `model_version` | text | e.g. `ProsusAI/finbert`, a pinned commit hash — see [ml-pipeline.md](ml-pipeline.md) |
| `positive_prob`/`neutral_prob`/`negative_prob` | `NUMERIC(6,5)` | each `CHECK BETWEEN 0 AND 1` |
| `predicted_label` | `VARCHAR(20)` | `CHECK IN ('positive','neutral','negative')` |
| `processed_at` | `TIMESTAMPTZ` | when this model version actually scored the article |

**Indexing:** `UNIQUE (article_id, model_version)` is both the idempotency key and the lookup
index every sentiment-aggregation query uses.

Full table-by-table schema for later domains is documented here as each migration lands (see the
phased build plan for the ordering).
