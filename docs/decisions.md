# Architecture Decision Records

Append-only log. Each entry: context, decision, consequences. Numbered sequentially.

---

## ADR-001: `ml/` is an independent package, never imported for training from the API

**Context:** The spec requires that long-running model training never block or run inside a
FastAPI request handler.

**Decision:** `ml/` is a sibling package to `backend/`, with its own `pyproject.toml`, importable
without FastAPI installed. `backend/app/services/forecast_service.py` (Phase 6) is the only
backend code that imports from `ml` — specifically `ml.inference`, never `ml.training` or
`ml.pipelines`. Celery workers (`backend/app/workers/tasks/`) import `ml.pipelines` for training
and backtesting.

**Consequences:** Enforces the rule structurally rather than by convention. `ml/` is
independently testable and could be extracted to its own repo/package registry later without
touching `backend/`.

---

## ADR-002: Provider abstraction, one ABC per phase that needs it (amended in Phase 3)

**Context:** The application must run end-to-end with zero paid API keys, while still being able
to plug in real market-data/news/fundamentals providers later without rewriting services.

**Original decision (Phase 1, not what was built):** A single `app/providers/base.py` would define
`MarketDataProvider`, `NewsProvider`, and `FundamentalsProvider` up front, with one grab-bag
`app/providers/mock/` implementing all three.

**What Phase 2/3 actually built, and why this ADR is amended rather than followed as-is:** Adding
ABCs for News/Fundamentals before any phase consumes them would be exactly the "unused
abstraction" the project's own engineering standard forbids — an interface with zero
implementations and zero callers is dead weight, not future-proofing. Instead: `app/providers/base.py`
gains one ABC per phase that actually needs it (`MarketDataProvider` in Phase 3; `NewsProvider`/
`FundamentalsProvider` will be added the same way in their phases, not before). Each provider
family gets its own subpackage with a `get_<x>_provider()` registry function selecting an
implementation based on `DEMO_MODE` — `app/providers/email/` (Phase 2, `ConsoleEmailProvider`) and
`app/providers/market_data/` (Phase 3, `DemoMarketDataProvider`) — rather than one shared
`registry.py` grab-bag or `mock/` directory.

**Consequences:** Services and routes depend on the ABC only — never a concrete provider — so a
real vendor is a registry-function change, not a service change (proven in Phase 3:
`DemoMarketDataProvider` and a hypothetical real one are interchangeable behind
`MarketDataProvider`). The cost is one more subpackage per provider family instead of a single
`mock/`; judged worth it for keeping unrelated providers (email, market data, eventually news)
independently testable and independently swappable.

---

## ADR-003: Postgres as source of truth, `NUMERIC` for all money/return values

**Context:** Financial calculations (P&L, returns, prices) must not accumulate floating-point
error.

**Decision:** Every price, return, and money column is `NUMERIC(18,6)`, never `FLOAT`/`REAL`.

**Consequences:** Slightly more verbose Python-side handling (use `Decimal`, not `float`, in
services touching these columns), in exchange for exact arithmetic.

---

## ADR-004: Structured JSON logging via `structlog`, health vs. readiness split

**Context:** `/health` (liveness) must never depend on external services, so an orchestrator
doesn't kill a healthy-but-momentarily-DB-less process; `/ready` must reflect real dependency
health.

**Decision:** `/health` returns a static `{"status": "ok"}` with no I/O. `/ready` performs a live
`SELECT 1` against Postgres and reports `unavailable` with a detail message on failure. Both are
mounted directly on the FastAPI app, outside `/api/v1`, since they're infra probes, not product
API surface.

**Consequences:** Docker/orchestrator health checks target `/health`; deployment readiness gates
target `/ready`.

---

## ADR-005: JWT access tokens + rotated opaque refresh tokens in an httpOnly cookie

**Context:** Phase 2 needs a token strategy that (a) never exposes a long-lived credential to
JavaScript (XSS blast-radius reduction), (b) can detect refresh-token theft/reuse, and (c) doesn't
require a server-side lookup on every request.

**Decision:** Access tokens are short-lived (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 15) JWTs
(HS256), returned in the response body only and held in memory client-side (`authStore`, not
persisted — see `frontend/src/stores/authStore.ts`). Refresh tokens are high-entropy opaque
strings (`secrets.token_urlsafe`), set as an `httpOnly`, `SameSite=Lax` cookie scoped to
`/api/v1/auth`, and rotated on every use: `POST /auth/refresh` revokes the presented session row
and issues a new access/refresh pair (`sessions` table, `app/services/auth_service.py`). Only the
SHA-256 hash of a refresh/reset token is ever persisted (`app/core/security.py`), matching how
passwords are handled — a database leak alone cannot produce a usable token.

**Consequences:** Reusing an already-rotated refresh token is detectable (the old session row is
already revoked) but this phase does not yet *react* to detected reuse (e.g. revoking every
session for that user) — a hardening item for a later phase. Access-token revocation is not
instant on logout/password-change for requests already in flight with a cached token, since JWTs
are stateless up to their own expiry; `access_token_expire_minutes` bounds that window. Every
password-changing action (`change-password`, `reset-password`) revokes all of that user's
sessions, forcing re-login everywhere else.

## ADR-006: `audit_logs.user_id` uses `ON DELETE SET NULL`, not the usual `CASCADE`

**Context:** `docs/database.md`'s default convention is `ON DELETE CASCADE` for rows owned by a
user. Account deletion (`DELETE /users/me`) records an `ACCOUNT_DELETED` audit entry and then
deletes the user in the same transaction.

**Decision:** `audit_logs.user_id` is the one intentional exception: `ON DELETE SET NULL`. The
audit trail is meant to outlive the account it's about, so deleting a user anonymizes their past
audit rows instead of erasing them.

**Consequences:** Audit rows for a deleted user show `user_id = NULL` and can no longer be joined
back to `users` for attribution (email, name, etc.) — only whatever a given action already wrote
into its own `metadata` JSONB survives. Today only `LOGIN_FAILED` captures anything into
`metadata` (the attempted email); if later phases need durable post-deletion attribution for other
actions, they must snapshot the relevant fields into `metadata` at write time.

## ADR-007: Demo Mode market data uses real tickers with synthetic prices, not fabricated-and-unlabeled or fictional-company data

**Context:** The app must run with zero paid API keys (spec: "provide a local seeded dataset... do
not fabricate production market data"), but a Stock Explorer full of invented company names would
be a worse demo than one showing recognizable names.

**Decision:** `DemoMarketDataProvider` (`app/providers/market_data/demo.py`) uses a fixed universe
of ~10 real, well-known tickers (AAPL, MSFT, ...) with real company/sector metadata, but entirely
*synthetic* price history — a seeded random walk from a fixed genesis date, not real historical
prices. Every `securities` row carries `data_source = 'demo'`, returned in every stock API response
and shown as a persistent banner in the frontend (never silently dropped).

**Consequences:** Nobody can mistake a demo price for real market data if they read the API
response or the UI, since the label is structural (a DB column, not a comment). The trade-off:
the label must actually be threaded through every new stock-data endpoint — a code-review
checklist item; a real provider integration flips `data_source` to `'external'` and nothing else
about the schema or API shape changes.

## ADR-008: `price_bars.ts` is `TIMESTAMPTZ`, not `DATE`, even though Phase 3 only stores daily bars

**Context:** Phase 3 ingests one bar per business day. A future phase may add intraday bars
(spec's Advanced Market Chart lists 1D/5D views, which need finer granularity than daily closes).

**Decision:** Store `ts` as `TIMESTAMPTZ` (daily bars at UTC midnight) rather than `DATE`.

**Consequences:** Intraday bars are an additive change (more rows, no type change, no migration
touching existing data) instead of a breaking one. Costs 4 extra bytes per row and requires UTC
normalization discipline in code that constructs `ts` — judged worth it versus a future migration
that would need to rewrite the column type under live data.

## ADR-009: One generic `jobs` table, not one table per job type

**Context:** Market-data ingestion needs job tracking now; the spec's build plan adds more
background job types later (model training, backtests, news processing, report generation).

**Decision:** A single `jobs` table (`app/db/models/job.py`) with a `job_type` discriminator column
and a `metadata` JSONB column carrying type-specific shape, rather than `ingestion_jobs`,
`training_jobs`, `backtest_jobs`, etc. as separate tables.

**Consequences:** One `GET /api/v1/jobs/{id}` endpoint and one admin "Jobs" view (Phase 12) work
for every job type, present and future, with no endpoint sprawl. The trade-off is weaker schema
enforcement on `metadata`'s shape per `job_type` — acceptable since job metadata is
read-mostly/diagnostic, not queried or joined on by other tables.

## ADR-010: Redis stock-data cache uses fixed short TTLs, not write-time invalidation

**Context:** `GET /stocks`, `/stocks/{ticker}`, and `/stocks/{ticker}/prices` are read-heavy and
only actually change when an ingestion job completes (at most a few times a day in Demo Mode).

**Decision:** `app/core/cache.py` caches these responses with fixed TTLs (30-60s) and no
invalidation hook on ingestion completion. A cache read/write failure (Redis down) is swallowed
and treated as a cache miss — caching must never turn a Redis outage into a user-facing 500.

**Consequences:** After an ingestion job completes, freshly-ingested data can take up to the TTL
to appear in these endpoints — an accepted staleness window, not a bug, given how infrequently the
underlying data changes. If a future phase needs read-your-writes right after ingestion (e.g. a
"view results" link at the end of an ingestion UI flow), that flow should bypass the cache
explicitly rather than this default policy changing for everyone.

## ADR-011: One SQL window-function query for "latest quote across N securities", not one query per security

**Context:** Phase 3's `GET /stocks` computed each row's quote with `PriceBarRepository.
get_latest(security_id=...)` inside a per-security loop — an N+1 query pattern that was
tolerable at ~10 demo securities but explicitly flagged as a Phase 4 audit finding, and would
have been *required* by the dashboard anyway (movers/breadth/sectors need "latest quote" for
every tracked security, not one page of them).

**Decision:** `PriceBarRepository.get_latest_quotes(security_ids=None)` computes, in one query,
each security's latest bar joined with `LAG(close) OVER (PARTITION BY security_id ORDER BY ts)` —
the close of the immediately preceding bar — using `ROW_NUMBER() OVER (PARTITION BY security_id
ORDER BY ts DESC) = 1` to pick the latest row per security. Both the stock list endpoint (passing
the current page's ids) and the dashboard (passing no filter, i.e. every security) now share this
one method.

**Consequences:** `GET /stocks` and `GET /dashboard/overview` are each O(1) queries against
`price_bars` regardless of how many securities exist, not O(n). The composite `(security_id, ts)`
index already added in Phase 3 (for idempotent upserts) is exactly what this window function
needs — no new index was required. Verified directly: `tests/integration/
test_price_bar_repository.py` asserts `prev_close` comes from the second-to-last bar
chronologically with 3+ bars present (a regression here — e.g. picking the earliest bar instead
of the immediately preceding one — would silently corrupt every return calculation and would not
be caught by a 2-bar-only test).

## ADR-012: Dashboard aggregates use one shared reference date, not each security's own latest bar

**Context:** Securities can, in principle, have different "latest bar" dates (e.g. one ingested
today, another ingested with an older `end_date`). Comparing "security A's move on Monday" against
"security B's move on Friday" and calling the result "market breadth" would not be a real
breadth measure.

**Decision:** `market_movers`, `sector_overview`, and `market_breadth` all filter to securities
whose own latest bar equals the single most recent `ts` across all of `price_bars` (the `as_of`
date returned in each section). A security excluded by this filter still appears in
`market_summary` (it has data, just not as-of-date data) and `recent_activity` (which is
explicitly "what changed recently," not reference-date-bound) — it just doesn't count toward
gainers/losers/breadth/sector averages for a date it wasn't actually measured on.

**Consequences:** In the common case (all securities ingested together, as Demo Mode's "ingest the
full universe" does), every security shares the same latest date and nothing is excluded — this
only matters for partial/staggered ingestion. Verified by
`tests/integration/test_dashboard_service.py::TestMarketMovers::
test_excludes_security_whose_latest_bar_predates_the_reference_date`, which hand-crafts exactly
that scenario.

## ADR-013: Daily return is the single canonical formula in the codebase, not reimplemented per endpoint

**Context:** A real cross-check during Phase 4 manual E2E testing (comparing `GET
/dashboard/overview`'s `change_percent` for a security against that same security's
`GET /stocks/{ticker}` `change_percent` on the same day) found the two disagreed — in the 20th
decimal digit, not the 2nd, but disagreed nonetheless. Root cause: `dashboard_service.py` and
`market_data_service.py` independently implemented two algebraically-equivalent but not
bit-identical formulas (`(close/prev - 1) * 100` vs `((close - prev) / prev) * 100`) — Decimal
arithmetic's fixed-precision context doesn't guarantee two equivalent expressions round to the
same value.

**Decision:** `market_data_service.compute_price_change(close, prev_close)` is the one formula.
`dashboard_service.compute_return_percent` calls it and returns just the percent component,
rather than maintaining its own expression.

**Consequences:** Every endpoint that reports a daily return now provably agrees with every other
one, because there is exactly one code path computing it. This bug would not have been caught by
either module's own unit/integration tests in isolation — each was internally consistent — only a
cross-endpoint check surfaced it, which is why the Phase 4 manual E2E script specifically
cross-checks a dashboard mover's `change_percent` against `/stocks/{ticker}`'s.

## ADR-014: Every ORM `datetime` column is explicitly timezone-aware via `Base.type_annotation_map`, not per-column

**Context:** Every model declared `Mapped[datetime]` with no explicit column type. SQLAlchemy's
default mapping for a bare `datetime` annotation is a naive `DateTime` (no timezone) — but every
Alembic migration explicitly created `TIMESTAMP(timezone=True)` columns. This mismatch was
invisible in Phase 2/3 because nothing had yet compared a naive DB value against an aware
`datetime.now(UTC)` in a way that raised — except it had, twice: `SessionRepository.is_valid` and
`PasswordResetRepository.is_valid` each carried a defensive `if expires_at.tzinfo is None:
expires_at = expires_at.replace(tzinfo=UTC)` precisely because of this, without the root cause
ever being fixed. Phase 4's `dashboard_service.compute_freshness_status` hit the same mismatch
head-on as a hard `TypeError` ("can't subtract offset-naive and offset-aware datetimes"), caught
by the integration test suite — not by inspection.

**Decision:** `app/db/base.py`'s `Base` now declares `type_annotation_map = {datetime:
DateTime(timezone=True)}`, so every `Mapped[datetime]` column across every model — present and
future — is timezone-aware without repeating `DateTime(timezone=True)` at each of the ~16 call
sites. This also means `Base.metadata.create_all()` (what the test suite uses to build schema)
now produces the *same* column types as the Alembic migrations (what dev/prod use) — the deeper
issue, since the two had silently diverged. The defensive `.tzinfo is None` patches in
`SessionRepository`/`PasswordResetRepository` were removed as now-provably-dead code, and
`PriceBarRepository.upsert_many` was updated to construct explicitly UTC-aware timestamps
(`datetime.combine(..., tzinfo=UTC)`) rather than naive ones, for the same reason.

**Consequences:** No existing migration needed to change (they already declared
`TIMESTAMP(timezone=True)`) — only the ORM side needed to catch up to match them. Every future
model gets this correctly by construction; a future column can still opt out with an explicit
`mapped_column(DateTime(timezone=False))` if a genuine naive-timestamp need ever arises, though
none exists today.

---

## ADR-015: A separate `ResearchDataProvider` for ML, never `DemoMarketDataProvider`

**Context:** Phase 3's `DemoMarketDataProvider` generates synthetic prices for the backend UI's
demo mode, clearly labeled as such (ADR-007). Phase 5 needed real historical OHLCV to train models
on, and the project's explicit rule is that ML results must never be reported as meaningful
financial performance if trained on that synthetic data.

**Decision:** `ml.data.research_provider.ResearchDataProvider` is a new, separate ABC, structurally
unconnected to `backend/app/providers/market_data/` (`ml/` cannot import `backend/` anyway — ADR-001).
`SampleSP500ResearchProvider` is the one implementation, backed by a real, MIT-licensed historical
dataset (`ml/ml/data/sample_data/research_sample_sp500.csv`, provenance in the adjacent
`PROVENANCE.md`) rather than a live scrape (Stooq requires solving a JS proof-of-work challenge to
script; Yahoo Finance 429s; FRED lacks per-ticker OHLCV — see ml-pipeline.md). Every dataset this
provider (or `DemoMarketDataProvider`) returns is stamped with a `DataEnvironment` enum
(`DEMO`/`RESEARCH`/`PRODUCTION`) via `DatasetProvenance`, so no downstream code can conflate the
two without the stamp being visibly wrong.

**Consequences:** A future real-vendor historical provider plugs in behind the same ABC without
touching feature/dataset/model code. The current sample is small (11 tickers, 5 years) and not
split-adjusted — acceptable for validating the pipeline's methodology, explicitly documented as
insufficient for a real performance claim (ml-pipeline.md "Known limitations").

---

## ADR-016: Predict return, not price; classification thresholds from training data only

**Context:** The spec explicitly forbids training a model to predict an exact future stock price
and presenting that as meaningful. A price target's scale depends on ticker/era (preventing a
shared model across names) and rewards a model for tracking the current price rather than
forecasting change.

**Decision:** `ml.targets.targets.future_return` is the one regression target
(`close_{t+h}/close_t - 1`, `h=5` by default). The classification target's Bearish/Neutral/Bullish
thresholds are computed by `derive_classification_thresholds` from the **training split's own**
`future_return` distribution (`mean ± 0.5·std`) — never from validation or test, which would leak
the evaluation data's distribution into the label definition. `ml.config.TargetConfig`'s fixed
`±2%` fallback is a pre-registered, documented approximation (a 5-day return's ~1-std move for a
large-cap equity), not a value tuned against any run's test metrics.

**Consequences:** Thresholds vary slightly between runs/datasets (since they're data-derived), but
are always reconstructable from `ModelRecord.hyperparameters` and the recorded `thresholds` field
in each experiment's `metrics.json`. A future re-run on different data will not accidentally reuse
one dataset's thresholds on another.

---

## ADR-017: Chronological split only; scalers fit on the training split only

**Context:** Time-series data leaks catastrophically under a random/shuffled train/test split — a
model can "predict the past from the future." The spec explicitly forbids
`train_test_split(..., shuffle=True)` and forbids fitting any preprocessing on validation/test data.

**Decision:** `ml.datasets.temporal_split.chronological_split` applies one fixed set of date
boundaries identically across every ticker (train ≤ 2016-06-30, validation through 2017-06-30,
test after) — there is no gap or overlap by construction (validation starts the day after
`train_end`; test starts the day after `validation_end`). `ml.datasets.sequences.SequenceScaler`
is fit once, on the training sequence tensor only; validation/test are transformed with those
parameters, never refit.

**Consequences:** This is enforced by more than convention: `train_test_split`/`shuffle=True` is
never imported anywhere in the primary evaluation path, and
`tests/unit/test_sequences.py::TestSequenceScalerLeakage` proves numerically (not just via an
API-call check) that fitting on train-only produces different scaler parameters than fitting on
train+validation combined. A genuine walk-forward evaluation (multiple rolling windows) is deferred
to a later phase — this dataset's history is too short to support one meaningfully (ml-pipeline.md
"Known limitations").

---

## ADR-018: Financial evaluation is per-ticker, never a naive cross-ticker concatenation

**Context:** While wiring `ml.evaluation.financial.evaluate_strategy` into `run_experiment`, the
first version fed one ticker's test rows immediately followed by the next ticker's rows into a
single call. This is a real bug, not a modeling simplification: `evaluate_strategy`'s trade-detection
logic (`_extract_trades`) treats input as one continuous return stream, so a position that was truly
"long AAPL" on its last row would silently continue as "long AMZN" on the next row, compounding two
unrelated instruments' returns into one artificial "trade" and equity curve. On the real dataset
this produced implausible numbers (a >600% cumulative return over a 7-month test window).

**Decision:** `ml.evaluation.financial.evaluate_strategy_per_ticker` runs the identical
single-asset strategy independently for each ticker (own equity curve, own trade list, own cost
accounting) and reports both the full per-ticker breakdown and simple cross-ticker means. This is
the function `ml.pipelines.train_pipeline` now calls for every regression model, tabular and
sequence-based alike.

**Consequences:** Financial numbers are now per-instrument and plausible (see ml-pipeline.md "Real
experiment results"). This is still not a portfolio backtest — no cross-ticker capital allocation
or correlation is modeled, each ticker is scored as if it were the account's only position — a
real multi-asset backtest is Phase 6+ work. `tests/unit/test_evaluation_financial.py::TestEvaluateStrategyPerTicker`
directly verifies a large loss in one ticker never contaminates another's numbers.

---

## ADR-019: A JSON-file model registry, not MLflow

**Context:** The spec explicitly forbids introducing MLflow/Kubeflow-scale MLOps tooling "for
appearance" without a real requirement. Phase 5 still needs each trained model's metadata
(hyperparameters, dataset/feature version, train/val/test periods, metrics, artifact path, git
commit, status) to be queryable and comparable.

**Decision:** `ml.registry.registry.ModelRegistry` is a small, dependency-free, JSON-file-backed
store (`registry.json`) — `register`, `get`, `list_all`, `set_status`, `best_by_metric`. Model
artifacts themselves live on the filesystem under `output_dir/models/<name>/` (never in
PostgreSQL, never committed to git — `ml/experiments/` is gitignored).

**Consequences:** No new infrastructure, no new dependency, fully testable without a database
(`tests/unit/test_registry.py`, 11 tests). If/when the team genuinely outgrows a flat JSON file
(concurrent writers, needing a query language, etc.), that is the point to revisit — not before.

---

## ADR-020: LSTM and GRU share one implementation, differing only in cell type

**Context:** The spec requires a fair LSTM-vs-GRU comparison and explicitly warns against assuming
either one wins by default.

**Decision:** `ml.models._recurrent.RecurrentReturnModel`/`_RecurrentNet` implement the entire
training loop, scaling, early stopping, and serialization once, parameterized only by
`cell_type: Literal["lstm", "gru"]`. `LSTMReturnModel` and `GRUReturnModel` are thin,
`Model`-ABC-conforming wrappers that each pin one `cell_type`. Every hyperparameter (hidden size,
layers, dropout, learning rate, epoch budget, early-stopping patience) is identical between them by
construction — a performance difference in results reflects the recurrent cell, not an incidental
implementation difference (a different weight-init call, a different batching order, etc.).

**Consequences:** On the real dataset (see ml-pipeline.md "Real experiment results"), neither
model outperforms the other decisively, and both underperform XGBoost's return model on this small
sample — reported as observed, since the spec forbids assuming deep learning beats a tree ensemble
by default.

---

## ADR-021: `ml/` is consumed by the backend as an editable local package, not copied or vendored

**Context:** Phase 6 needed the backend to import `ml.inference`/`ml.explainability`/`ml.backtest`
for the first time (ADR-001 anticipated this: "`backend/app/services/forecast_service.py` is the
only backend code that imports from `ml`"). `ml/` and `backend/` have always been separate Python
environments (own `.venv`, own `requirements.txt`), and `infra/docker-compose.yml` already
bind-mounted `../ml:/ml` into the backend/worker containers since Phase 1, but nothing made the
package importable from either environment.

**Decision:** `ml/pyproject.toml` gained a minimal `[build-system]`/`[tool.setuptools.packages.find]`
so `pip install -e` works on it. The backend's venv (local dev/test) and its Docker containers
(`docker-compose.yml`'s `command:`, prefixed with `pip install -e /ml`) both install `ml/` as an
editable package — the identical mechanism in both places, so a code change in `ml/` is picked up
by the backend without a rebuild in either environment. `backend/requirements.txt` separately pins
the runtime subset `ml.inference`/`ml.explainability` actually need (`numpy`, `pandas`,
`scikit-learn`, `xgboost`, `shap` — identical versions to `ml/requirements.txt`), deliberately
excluding `torch`/`transformers` (the backend serves XGBoost only — ADR-022 covers why).

**Consequences:** No new infrastructure, no vendoring/copying of `ml/` source into `backend/` (which
would drift). `ml/experiments/` (registry + model artifacts) is read via `ML_REGISTRY_PATH`
(`app/core/config.py`), defaulting to `/ml/experiments/registry.json` in Docker; local (non-Docker)
dev/test overrides this to the real relative path via `.env`/`.env.test`. A missing registry is a
real, expected state (no training run yet), not an error to work around — see
`ml.inference.serving.ModelUnavailableError`, mapped to a `503`.

---

## ADR-022: The forecast/backtest APIs serve XGBoost only, selected by the registry

**Context:** Phase 5 produced four trained model types (naive baselines, XGBoost, LSTM, GRU).
Phase 6 needed to pick what the HTTP-facing forecast/backtest endpoints actually serve, and how
they pick *which* trained artifact.

**Decision:** `ml.inference.serving.load_forecast_models` always loads the best-by-metric
`xgboost_return` and `xgboost_direction` records from the registry (`ModelRegistry.best_by_metric`
— never an arbitrary filesystem path or a hardcoded "latest.pkl"), combining their return and
direction predictions into one `ForecastResult`. LSTM/GRU are not served over HTTP in this phase.

**Consequences:** XGBoost is both the best-performing model from Phase 5's real comparison
(docs/ml-pipeline.md "Real experiment results") and the cheapest to serve (no `torch` in the
backend's dependency footprint, `shap.TreeExplainer` is exact and fast for it) — serving it first
is not a quality compromise. If the registry's best model changes after a future retraining run,
the API automatically picks it up (no code change) as long as it's still an `xgboost_return`/
`xgboost_direction` record; serving a different model *type* (e.g. LSTM) is future work requiring
the backend to add `torch` and a corresponding `ml.explainability` path for it.

---

## ADR-023: Demo-data forecasts/backtests are disclosed, not blocked

**Context:** This deployment's `price_bars` are, by default, `DemoMarketDataProvider`'s synthetic
random walk (ADR-007) — a different price regime entirely from the real historical data
(`RESEARCH_DATASET_VERSION`) the registered models were trained on. Feeding demo data through a
model trained on real data produces a technically-valid-shaped prediction with no real predictive
meaning. The spec's data-environment rules (Phase 5) require this never be blurred.

**Decision:** Neither `forecast_service.py` nor `backtest_service.py` blocks inference against
demo data — doing so would make the served-forecast/backtest feature undemoable in the one
environment this project ships with data in by default. Instead, every response carries
`data_source` (`ForecastResponse`/`BacktestResponse`, reusing the security's own already-existing
`data_source` field, ADR-007's precedent) plus an explicit `disclaimer` field, and the frontend
(`ForecastCard`, `BacktestPage`) surfaces both prominently rather than in a tooltip.

**Consequences:** The feature is demoable end to end today, honestly labeled throughout. A future
deployment pointed at a real market-data provider would automatically show `data_source: "external"`
on the same responses, and only then would a forecast's numbers reflect the model's actual
validated research performance — no code change needed to make that transition meaningful, only a
real data source.

---

## ADR-024: `ml.backtest` is a new package, separate from Phase 5's per-ticker evaluation

**Context:** Phase 5's `ml.evaluation.financial.evaluate_strategy_per_ticker` (ADR-018) answers "how
would this one ticker's signal have performed in isolation" — deliberately not a portfolio
question. Phase 6 needed an actual multi-asset portfolio backtest (shared cash, position sizing
across names, one consolidated equity curve).

**Decision:** `ml.backtest` (`contracts.py`, `signals.py`, `engine.py`, `metrics.py`,
`walk_forward.py`) is a new, separate package built on top of
`ml.inference.serving.generate_historical_predictions` — it does not modify or replace
`ml.evaluation.financial`, which remains the right tool for "is this one ticker's signal any good
in isolation." The portfolio engine's execution-timing and no-look-ahead guarantees are
independently tested (`tests/unit/test_backtest_engine.py::TestCriticalLeakageAndTimingTests`), not
inherited from Phase 5's tests.

**Consequences:** Two evaluation paths now coexist, deliberately: per-ticker (`ml.evaluation.financial`,
used inside `ml.pipelines.train_pipeline`'s per-experiment reporting) and portfolio-level
(`ml.backtest`, used by `POST /research/backtest`) — each answers a different, clearly-named
question, rather than one module trying to serve both and blurring the distinction Phase 5's
ADR-018 fix was specifically about establishing.

---

## ADR-025: News articles store provider-supplied summaries only, never full body text

**Context:** Phase 7 needed a canonical article model. Most news APIs' terms of service (and
plain copyright law) permit storing headline/metadata/a short summary, but not republishing full
article bodies without a specific license — and this project has no such license with any
provider.

**Decision:** `NewsArticle` has a `summary` column (nullable, provider-supplied only) and a
`content_status` field (`SUMMARY_ONLY`/`TITLE_ONLY`) — there is no `body`/`content` column at all,
structurally, not just a convention nobody happens to violate yet. `app/providers/base.py`'s
`NewsArticleData` (what every provider hands back) has the identical shape — a provider
implementation cannot even construct a full-body payload without changing the ABC itself.

**Consequences:** The sentiment model scores whatever `summary`/`title` a provider legitimately
supplies (`news_processing.sentiment_input_text`) — a shorter signal than a full article would
give, a real (documented) limitation, not a bug. A future real provider that only supplies
headlines (no summary) still works (`content_status="TITLE_ONLY"`); one that offers a licensed
full-text feed would need a deliberate schema change to add a body column, not something that could
happen by accident.

---

## ADR-026: Entity/ticker mapping via ticker-symbol + case-sensitive company-name matching, not NER

**Context:** Phase 7 needed to map article text to canonical securities. A full NER (named-entity
recognition) model would generalize better to an arbitrarily large, unknown universe of companies,
but this project tracks a small, fixed set of securities (the `securities` table), and the spec
explicitly warns that company names can collide with ordinary words (e.g. "Apple").

**Decision:** `app/services/entity_extraction_service.py` uses two precise, deterministic,
explainable signals instead: an explicit `$TICKER`/`(TICKER)` mention (confidence 0.95), and the
security's legal name with corporate suffixes stripped, matched **case-sensitively** (confidence
0.70) — case-sensitivity is the specific, deliberate mitigation for "Apple Inc." stripping to the
ordinary word "Apple": matching only the properly-capitalized form (as real financial journalism
actually writes a company name) rejects the lowercase fruit while still catching genuine coverage.
A match below `MIN_CONFIDENCE` (0.70) is never recorded — an unconfident article stays unmapped
rather than getting an invented ticker.

**Consequences:** No new ML dependency, fully deterministic and unit-testable (including the exact
"ordinary word" ambiguity case — see `tests/unit/test_entity_extraction.py::TestAmbiguityHandling`).
Lower recall than a real NER model on company names not well-represented by this heuristic (a
name that doesn't survive suffix-stripping into something specific enough, or referenced only by
an unusual abbreviation) — acceptable at this project's current scale (a handful of tracked
securities); revisit if/when the tracked universe grows into the hundreds and misses become
material.

---

## ADR-027: Backend adds `torch`/`transformers` for FinBERT — amends ADR-022

**Context:** ADR-022 (Phase 6) deliberately kept `torch` out of the backend's dependencies,
serving XGBoost only. Phase 7's financial sentiment model (FinBERT, `ml.nlp.sentiment`) is a
transformer model — there is no torch-free way to run it.

**Decision:** `backend/requirements.txt` now pins `torch==2.5.1`/`transformers==4.47.1`,
identically to `ml/requirements.txt`. `ml.nlp.sentiment.get_sentiment_analyzer()`'s process-wide
singleton cache means the model is loaded from disk once per backend/worker process, not per
request/article — the cost ADR-022 was originally trying to avoid (a heavy dependency for a
marginal feature) is paid once at a real, load-bearing feature's first use, not repeatedly.

**Consequences:** ADR-022's "no torch in the backend" is no longer categorically true — it was
correct for Phase 6 (serving XGBoost, the actually-best model, needs no torch) and remains correct
advice for *inference-only* additions that don't need a transformer model; Phase 7's sentiment
model is a genuine exception, not a reason to revisit XGBoost-serving. LSTM/GRU forecast serving
(still not exposed over HTTP) would ride on this same now-present dependency for free if a future
phase adds it.

---

## ADR-028: The demo news provider is a pure function of `(tickers, since, until)`, mirroring `DemoMarketDataProvider`

**Context:** `DemoMarketDataProvider` (Phase 3) is deterministic by explicit design — the same
`(ticker, start, end)` call always returns byte-identical bars, which is what makes ingestion
idempotency meaningfully testable rather than coincidental. Phase 7's `DemoNewsProvider` needed
the same property, but naive "recent news" fixtures often reach for wall-clock `datetime.now()`
internally, which would make re-fetching the same logical window non-reproducible.

**Decision:** `NewsProvider.fetch_articles` takes explicit `since`/`until` bounds (never an
implicit "provider's own default lookback" resolved internally) — the caller (`run_news_ingestion`,
mirroring `run_ingestion`'s `end_date or datetime.now(UTC)`) is the only place wall-clock time is
read. `DemoNewsProvider` places each templated headline at a fixed *fraction* of `[since, until]`,
seeded by `(ticker, template_index)` only — never by the window's actual dates — so the same window
always reproduces the same articles.

**Consequences:** `tests/unit/test_demo_news_provider.py::test_is_deterministic_for_the_same_window`
and the ingestion idempotency tests
(`tests/integration/test_news_sentiment_service.py::test_run_news_ingestion_is_idempotent`) are
real proofs, not assumptions. Article URLs also use the `.invalid` TLD (RFC 2606) specifically so
a clicked demo link fails obviously rather than resolving somewhere unintended.

---

---

## ADR-029: `LLMProvider` abstraction, real Anthropic implementation, and a cost-conscious default model

**Context:** Phase 8 needed the research agent's orchestration logic (`app/agent/orchestrator.py`)
to never depend on a specific LLM vendor SDK directly — the same reasoning already applied to
`MarketDataProvider` (Phase 3) and `NewsProvider` (Phase 7) via ADR-002's registry pattern. It also
needed the entire test suite to run without any external API credentials (a hard requirement, not
a nicety — CI and most dev environments have no LLM key), and needed a default model choice that
doesn't burn real money on every dev test run against a live provider.

**Decision:** `app/agent/llm_provider.py` defines `LLMProvider` (ABC: `complete()`, `model`,
`provider_name`), a real `AnthropicLLMProvider` (lazily imports the `anthropic` SDK, converts our
vendor-agnostic `LLMMessage`/`ToolDefinition` types to Anthropic's wire format, maps
`APITimeoutError`/`APIError` to a single `LLMProviderError`), and a `FakeLLMProvider` — a
deterministic test double scriptable with a fixed sequence of `LLMResponse | Exception` items
(letting a test simulate a provider timeout/failure mid-conversation), recording every call's
exact `(system, messages, tools)` for assertions. `get_llm_provider()` (the registry function,
`@lru_cache`d) raises a clean `LLMProviderError` — never falls back silently — when
`LLM_API_KEY` is unset. The default configured model, `claude-haiku-4-5-20251001`
(`Settings.llm_model`), is deliberately the smallest/cheapest current-generation model suitable for
a tool-calling research assistant, not the largest available — cost-consciousness by default,
overridable via `LLM_MODEL` for anyone who wants a larger model in their own deployment.

**Consequences:** The orchestrator, all tool tests, and the full evaluation suite
(`tests/integration/test_agent_evaluation.py`) run entirely on `FakeLLMProvider` — zero external
calls, zero cost, fully deterministic, and they run in CI with no secrets provisioned. The real
`AnthropicLLMProvider` path is implemented and unit-tested for its message/tool conversion logic,
but was not exercised against the live Anthropic API in this phase's own verification (no API key
was available in this sandboxed environment) — a stated, known limitation, not a gap papered over;
an operator with a real key gets the same guarantees the fake provider's tests already establish
for the orchestration logic around it, since the provider boundary is exactly where the two
implementations diverge.

---

## ADR-030: A fixed, closed set of 9 controlled tools — no arbitrary code execution, no vector DB

**Context:** Phase 8's spec is explicit that the agent must reason only through controlled,
typed tools — never through an `execute_sql`/`execute_python`/`execute_shell`/filesystem
tool, regardless of how convenient such a tool would be for covering an unanticipated question.
Separately, the phase is *named* around "AI research"/RAG-adjacent framing, which invites reaching
for a vector database by default — but AlphaLens has no long-form document corpus to index; its
retrievable content is either structured rows (prices, forecasts, sentiment, backtest metrics) or a
handful of recent news articles per ticker.

**Decision:** `app/agent/tools.py` defines exactly 9 tools (`get_stock_quote`,
`get_price_history`, `get_technical_indicators`, `get_forecast`, `get_forecast_explanation`,
`get_news`, `get_sentiment`, `get_sentiment_history`, `run_backtest`), each a thin wrapper over an
already-existing Phase 5-7 service/repository, each with its own Pydantic input schema validated
before the handler runs, and each catching its own relevant exception types to return a structured
`{"error": ...}` result rather than ever propagating a raw exception into the conversation. No
tool accepts arbitrary code, a raw SQL fragment, or a filesystem path. Retrieval is exact and
structured — a typed tool call against a repository/service, never embedding similarity search —
so no vector store is introduced; doing so would add real infrastructure (an index to build, keep
fresh, and operate) to solve a retrieval problem this system doesn't have.

**Consequences:** The tool surface can only grow through a deliberate, reviewed code change — the
LLM cannot expand its own capabilities at runtime by "creative" prompting, since there is no
generic-execution tool for it to be tricked into misusing. `tests/integration/test_agent_tools.py`
includes an explicit `test_no_arbitrary_code_execution_tools_exist` regression test asserting the
forbidden names never appear in the tool registry. If a future phase introduces a genuine long-form
corpus (research reports, filings, transcripts), that would be the point to reconsider a vector
store — not before, and not merely because "RAG" is in a phase's name.

---

## ADR-031: `POST /research/chat` rate-limited to 20/hour per client

**Context:** Every other endpoint in this API is backed by Postgres/Redis calls with negligible
marginal cost. `/research/chat` is different: a real LLM call has real latency (seconds, not
milliseconds) and, with a live provider, real dollar cost per request — the existing "no rate
limit needed" default for most routes doesn't hold here.

**Decision:** `@limiter.limit("20/hour")` (the same `slowapi`, IP-keyed limiter already used for
`/auth/*`, `app/core/rate_limit.py`) is applied to `/research/chat` specifically. 20/hour is
generous enough for genuine interactive research use (a handful of questions per session) while
bounding worst-case cost/load from a single client hammering the endpoint.

**Consequences:** A client exceeding the limit gets a `429` before the request ever reaches the LLM
provider — verified in `tests/api/test_research_chat.py::test_rate_limit_is_enforced`. Like the
auth endpoints' limiter, this is in-memory (correct for a single backend process); a Redis-backed
limiter store is the same follow-up already noted for auth once the API runs multi-instance.

---

## ADR-032: Conversation memory is bounded, in-process, and keyed by `(user_id, conversation_id)` — never persisted

**Context:** Multi-turn research questions need pronoun/reference resolution ("What about its
sentiment?" following a question about AAPL) to work, which requires some conversation memory. Two
risks needed a structural answer, not a policy one: (1) a client-supplied `conversation_id` is
guessable/reusable, so naive storage keyed only by that id would let one user's conversation leak
into another's; (2) storing full conversation transcripts durably raises retention/deletion
questions this phase's scope doesn't need to answer yet.

**Decision:** `app/agent/conversation.py::ConversationStore` is an in-memory, thread-safe dict keyed
by the compound tuple `(user_id, conversation_id)` — never by `conversation_id` alone — capped at
`DEFAULT_MAX_TURNS` turns (oldest trimmed first). `user_id` always comes from the authenticated
request's own bearer token, never from client input, so isolation is structural: even a client that
deliberately reuses another user's (guessed or observed) `conversation_id` string gets their own
independent, empty-or-own history, never the other user's.

**Consequences:** Conversation history is lost on process restart — acceptable for a research aid's
short-term working memory, and it sidesteps needing a retention/deletion policy for a durable chat
log this phase doesn't require. `tests/unit/test_agent_conversation.py` and
`tests/integration/test_agent_security.py::TestCrossUserConversationIsolation` (plus an HTTP-level
version in `tests/api/test_research_chat.py`) verify the isolation property directly, including the
specific case of two different users deliberately colliding on the same `conversation_id` string. A
future phase needing durable, resumable conversations across restarts/replicas would move this
store to Redis/Postgres behind the same `ConversationStore` interface — not a redesign, an
implementation swap.

---

## ADR-033: Evidence citation tags use a display-name map, not `str.title()`

**Context:** Every grounded answer cites its evidence inline using a short bracketed tag matching
the evidence's `source_type` (e.g. `[Forecast]`, `[SHAP]`, `[Market Data]`). The naive
implementation — `source_type.title()` — is wrong for two of the six source types:
`"SHAP".title()` produces `"Shap"` (SHAP is an acronym, not a word), and `"MARKET_DATA".title()`
produces `"Market_Data"` (the underscore never becomes the intended space).

**Decision:** `app/agent/evidence.py` defines an explicit `_DISPLAY_NAMES` dict mapping every
`EvidenceSourceType` value to its correct display string, and `Evidence.citation_tag()` looks up
that map (falling back to `.title()` only for a hypothetical future source type that hasn't been
given an explicit entry yet — a defensive default, not the primary path).

**Consequences:** `tests/unit/test_agent_evidence.py::test_shap_tag_is_all_caps_not_titlecased` and
`test_market_data_tag_has_a_space` pin this behavior directly, plus a
`test_every_source_type_has_a_tag` loop guarding against a future source type being added to
`EvidenceSourceType.ALL` without a corresponding display-name entry ever silently falling through
to a wrong-looking tag in a real user-facing answer.

---

## ADR-034: Groq and Gemini added as real `LLMProvider` implementations — orchestrator untouched

**Context:** Phase 8.5 required validating the research agent against two additional real LLM
vendors (Groq, Gemini) to prove the Phase 8 `LLMProvider` abstraction (ADR-029) actually
decouples the orchestration logic from a specific vendor, not just in principle. The explicit
constraint was that this must be provable by absence of change: the orchestrator, tools, evidence
model, prompts, and conversation store must require zero modification to add a provider.

**Decision:** `app/agent/llm_provider.py` gained `GroqLLMProvider` (targets Groq's OpenAI-compatible
chat-completions tool-calling API via the official `groq` SDK) and `GeminiLLMProvider` (targets
Gemini's native manual function-calling via the official `google-genai` SDK — `generate_content`
plus an explicitly-built `contents` list, with `automatic_function_calling` deliberately disabled
so the orchestrator, not the SDK, always owns the tool-calling loop). Each converts the exact same
`LLMMessage`/`ToolDefinition`/`ToolCallRequest` types every other provider uses to and from its own
wire format internally; `app/agent/orchestrator.py` was not modified at all to support them — the
diff for this phase touches only `llm_provider.py` (new provider classes + message-conversion
helpers) and `app/core/config.py` (new settings: `LLM_PROVIDER`, `GROQ_API_KEY`/`GROQ_LLM_MODEL`,
`GEMINI_API_KEY`/`GEMINI_LLM_MODEL`). `LLM_PROVIDER` (default `"anthropic"`) selects which one
`get_llm_provider()` builds; each provider requires its own key and never falls back to a
different provider than the one explicitly selected.

One real dependency consequence: `google-genai` requires `pydantic>=2.12.5`, forcing this project's
pinned `pydantic` up from `2.10.4` to `2.13.5` — verified safe by running the full pre-existing
276-test backend suite against the new pin before adding any Phase 8.5 code, and again after
(unchanged pass count both times).

Both providers explicitly avoid vendor-specific *built-in* tools — Groq's server-side web-search/
code-execution and Gemini's `google_search`/`code_execution`/`computer_use`/etc. — declaring only
AlphaLens's own 9 function tools via each vendor's plain function-calling primitive. This isn't a
new decision so much as ADR-030's tool-boundary property extended to two more vendors: the boundary
is what this codebase declares to a vendor API, not a property any one vendor's SDK enforces for
free.

**Consequences:** `tests/unit/test_agent_groq_provider.py` and `test_agent_gemini_provider.py`
mock at the SDK client-method boundary using each vendor's own real Pydantic response/exception
types (not bare `Mock` objects), covering tool-schema conversion both directions, response parsing,
and every documented provider failure mode (missing/invalid key, rate limit, timeout, malformed
response, safety-blocked response) mapping to the existing `LLMProviderError` →
`AGENT_UNAVAILABLE` 503 path. `tests/integration/test_agent_live_providers.py` re-runs (a subset
of) the Phase 8 evaluation questions against the real Groq/Gemini APIs when their keys are present,
independently cross-checking each scenario's returned `Evidence` against a direct call to the same
underlying tool — marked `@pytest.mark.live_llm` and registered in `pyproject.toml`'s
`markers` so `pytest -m live_llm` selects them explicitly while a plain `pytest` run continues to
require no LLM credentials at all (every test in that file is individually `skipif`-gated on its
own key's presence).

**Update — live validation actually run:** with real credentials supplied, `pytest -m live_llm`
was executed against both providers. **Groq: 11/11 real scenarios passed** on a clean run (tool
selection, grounding-vs-direct-tool-call evidence matching, citations, missing-data handling,
prompt-injection resistance, and refusal behavior all verified against actual model output — see
ADR-035 for the one real bug this surfaced, and the Phase 8.5 report for the full comparison
table). **Gemini's implementation defect (wrong role convention) was found and fixed via this live
run** — see ADR-035 — after which Gemini's remaining live scenarios could not be fully validated
in this session because the configured key is on Google's free tier, which enforces a **hard quota
of 20 `generate_content` requests per day per model** (`gemini-3.8-flash`); a real
`429 RESOURCE_EXHAUSTED` response was observed and is the documented reason, not a code defect —
see the Phase 8.5 report's known limitations.

---

## ADR-035: Gemini's function-response turn uses `role="user"`, not `role="tool"` — found via live validation

**Context:** ADR-034 documented `GeminiLLMProvider`'s message conversion as originally implemented
against `google-genai`'s documented types, using `role="tool"` for the `Content` turn carrying a
tool's result back to the model (analogous to Groq/OpenAI's `"tool"` role and Anthropic's
tool-result-as-`"user"`-content-block convention). This was based on SDK/documentation research
only — Phase 8's own explicit requirement (Step: "if Gemini's function-response role/convention
behaves differently from what was assumed during implementation, correct the provider
implementation according to the actual SDK/API behavior") anticipated exactly this risk.

**What actually happened:** the first live run against a real Gemini API key failed every
multi-turn (tool-calling) scenario with a real `400 INVALID_ARGUMENT` response:

> Role 'tool' is not supported. Please use a valid role: SYSTEM, SYSTEM_1, USER, ASSISTANT,
> DEVELOPER, CONTEXT, USER_CONTEXT, MODEL, USER.

The classic `generate_content` + manually-built `contents` surface (the non-"Interactions API"
path this provider deliberately uses, per ADR-034's reasoning about the orchestrator owning the
loop) does not accept `"tool"` as a role at all.

**Decision:** `_to_gemini_contents()` now emits `role="user"` for the `Content` wrapping a
`FunctionResponse` part — the same role Anthropic's provider already uses for tool-result content
(both vendors model a tool result as something the "user" side of the conversation is supplying
back to the model, distinct from `"model"`, which is reserved for the model's own prior turns
including its function-call requests).

**Consequences:** Fixed with zero change to the orchestrator, tools, or evidence model — confirmed
by an immediate live rerun: every previously-400-failing Gemini scenario progressed past message
construction (the same run then hit a real, unrelated `429` quota limit — see ADR-034's update —
not a repeat of this bug). Two regression tests pin the fix directly against `_to_gemini_contents`
(`tests/unit/test_agent_gemini_provider.py::TestGeminiMessageConversion`): one asserts a `"tool"`-
role `LLMMessage` converts to `Content(role="user", ...)`, the other asserts an assistant tool-call
turn still converts to `role="model"`. This is the concrete justification for Phase 8.5's mandatory
live-validation requirement in the first place — the equivalent mocked-SDK unit tests (which
construct `google-genai`'s own real response *types* but never make a real HTTP call) could not
have caught this, since nothing before this fix ever exercised the actual Gemini API's request
validation.

---

## ADR-036: Portfolio accounting is average-cost, long-only, and stores no derived state

**Context:** Phase 9 needed a real (not simulated) portfolio accounting model. FIFO/LIFO lot
tracking, short selling, margin, and time-weighted returns are all legitimate choices a production
brokerage might make, but each adds real complexity (per-lot cost tracking, borrow/margin-call
logic, cash-flow-adjusted daily return calculation) that this phase's own instructions explicitly
said not to build unless "the existing architecture makes it trivial and correctly supported."

**Decision:** `Transaction` rows are the only persisted financial fact — `Portfolio` has no
`cash_balance`/`total_value` column, and no service ever writes one, so there is no "derived state
drifted out of sync with reality" failure mode to guard against. `app/services/portfolio_service.py`
recomputes cash/positions/P&L fresh from the full transaction history (`replay_transactions`, a
pure function with no I/O) plus current prices on every call. Cost basis is **average-cost**: a
position's `total_cost` is one running total divided by quantity; a partial `SELL` removes cost
basis at that average, never tracking which specific earlier lot was sold. Positions are
**long-only**: `create_transaction` checks the replayed ledger's current holding before accepting a
`SELL` and raises `InsufficientPositionError` if it would go negative — short selling is rejected,
not silently allowed. Fees are added to cost basis on `BUY` (correctly reducing future unrealized
gains) and subtracted from proceeds on `SELL` (correctly reducing realized gains); `CASH_DEPOSIT`/
`CASH_WITHDRAWAL` carry no fees, enforced by the `ck_transactions_type_fields` DB constraint —
modeling a brokerage transfer, not a wire-fee scenario. `total_return_percent` is a simple
money-weighted return, `(total_value - net_contributed) / net_contributed` — explicitly **not**
time-weighted, which would require a cash-flow-adjusted daily calculation this phase does not
build.

**Consequences:** `tests/unit/test_portfolio_service.py` exercises `replay_transactions` as a pure
function (no DB) for average-cost math, fee treatment on both BUY and SELL, and realized P&L on a
partial sell. `tests/integration/test_portfolio_service.py` covers the DB-backed paths: cash/
position validation rejecting an overdraw or an over-sell, idempotency (a repeated
`idempotency_key` returns the existing transaction rather than double-applying), and a holding with
no ingested price data rendering `market_value: null` rather than a fabricated zero
(`market_value_is_partial` on the analytics response makes a partial/unknown total explicit rather
than silently understating it). If a future phase needs FIFO lots, short positions, or margin, this
average-cost/long-only model is the documented boundary to extend, not retrofit silently.

## ADR-037: No-look-ahead portfolio performance history via per-day transaction/price replay

**Context:** A portfolio value time series is one of the easiest places to accidentally leak
future information into a historical point — e.g. building "value as of day D" from the *current*
full transaction list (including transactions dated after D) or from the *latest* price (rather
than the price actually known on day D). Phase 9 explicitly required a dedicated adversarial test
proving this can't happen.

**Decision:** `get_performance_history` builds its timeline from the union of every transaction's
date and every price bar's date, then for each day `D` independently: replays only transactions
with `executed_at.date() <= D` (via `replay_transactions` on a filtered slice, the same pure
function everything else uses) and prices any open position using only that security's price bars
with `ts.date() <= D` — the latest such bar, found via `bisect_right` on a precomputed ascending
`(dates, closes)` series per security (built once from a single batched
`PriceBarRepository.get_bars_for_securities` call across every security ever held, not one query
per day). A day with an open position but no as-of price yet renders `market_value: None` for that
point, not a zero or an extrapolated guess.

**Consequences:** `tests/integration/test_portfolio_service.py::TestNoLookAheadBiasPerformanceHistory`
directly proves the property: recording a transaction dated "now" after computing history for a
`past` date leaves that past point's `cash`/`net_contributed` unchanged, and a second test walks
every computed point and confirms its implied per-share price always traces back to a real price
bar dated on or before that point's day, never a later one. A portfolio with no transactions yet
returns `available: False` with a `reason`, never an empty-but-technically-valid series presented
as "no history."

## ADR-038: Screener reuses forecast models against already-fetched OHLCV — zero extra DB queries per security; sentiment is the one documented exception

**Context:** A screener that computes forecast/technical/sentiment fields for N securities is the
single place in this codebase most exposed to N+1 query risk — every existing per-ticker endpoint
(`/stocks/{ticker}/forecast`, `/stocks/{ticker}/sentiment`) fetches that ticker's own history with
its own query, which is correct for one ticker but would be N queries for N screener rows.

**Decision:** `run_screener` fetches the entire candidate universe's data in three batched calls
regardless of N: `SecurityRepository.list_matching` (sector/ticker-substring filter, still SQL),
`PriceBarRepository.get_latest_quotes` (one windowed query for every security's latest quote), and
`PriceBarRepository.get_bars_for_securities` (one query for every security's trailing OHLCV,
grouped in memory by `security_id` — a handful of securities' worth of rows is a trivial in-process
grouping, not a database round-trip). Forecasts are computed by slicing that already-fetched OHLCV
per security into the same `ml.inference.serving.build_latest_feature_row` pipeline
`forecast_service` uses for one ticker — the identical feature computation, just fed from memory
instead of a fresh query. `ml_common.load_models()` is called once per screener request (it's
already an in-process, mtime-invalidated cache — see `ml_common.py`'s own docstring — so even that
one call is nearly free on a warm cache). Sentiment is the deliberate exception:
`news_query_service.get_sentiment_overview` still runs its own aggregation query pair per
candidate, since `news_sentiment_aggregation.py` was never built to batch across securities. This
is accepted as a bounded, documented tradeoff for a small demo security universe (tens of
securities, not thousands) — a screener over a materially larger universe would need a batched
sentiment aggregation query added to that module, which is out of scope for Phase 9.

**Consequences:** `tests/integration/test_screener_service.py` proves the batching didn't silently
turn into fabrication: a security with no price bars gets `last_price: null` (not 0), one with
fewer than 21 days of history gets `return_20d_percent: null`, and a ticker outside the trained
model's universe gets `forecast_direction: null` — each also listed in that row's
`unavailable_fields` — and filtering by `forecast_direction` excludes rows with no forecast rather
than treating "unknown" as a match. Pagination determinism is also directly tested: the same
filters/sort always return the same page in the same order, because the base universe query is
always `ticker ASC` and Python's `sort()` is stable, so ties on any other sort field still break by
ticker.

## ADR-039: Alert evaluation reuses the generic `jobs` table; cooldown + row-level locking make it idempotent under concurrent workers

**Context:** ADR-009 established `jobs` as a deliberately generic background-job tracking table so
later phases (training, backtests, news processing) would extend `JobType` rather than each growing
its own tracking table. Phase 9's alert engine needed the same kind of "did this scheduled run
happen, did it fail" observability Celery Beat's periodic task requires — but also needed a
correctness property no prior job type did: preventing a still-true condition from firing a new
`AlertEvent` on every evaluation cycle, and preventing two concurrent evaluations of the same alert
from double-firing.

**Decision:** Alert evaluation adds `JobType.ALERT_EVALUATION` to the existing `jobs` table rather
than a new one (`app/workers/tasks/alerts.py` mirrors `market_data.py`'s job-lifecycle shape
exactly: create+commit the job row before doing any work, so a mid-run crash still records
`FAILED`). Cooldown/deduplication is `cooldown_minutes` + `last_triggered_at` on `Alert`: a
condition that re-evaluates true before the cooldown window elapses is silently skipped
(`skipped_cooldown`, not a new event). The two CHANGE-detection alert types
(`FORECAST_CLASS_CHANGE`, `SENTIMENT_CHANGE`) need a previous observed value to diff against, which
nothing else persists — `Alert.last_observed_state` (a JSONB scratch column, distinct from the
user-facing, append-only `AlertEvent` history) is the evaluator's own memory of "what did I last
see," updated every cycle regardless of whether the alert fires; the first evaluation after
creation only establishes this baseline and never fires. For concurrency, each alert's
check-then-fire sequence runs against a row locked with `SELECT ... FOR UPDATE`
(`app/services/alert_evaluation_service.py::evaluate_all_alerts`) — a second worker (or a second
Beat-triggered run overlapping the first) evaluating the same alert blocks on that lock until the
first's transaction commits, then re-reads the now-updated `last_triggered_at` and correctly skips
under cooldown rather than racing past the check and firing twice. This is a plain PostgreSQL row
lock, not a new distributed-locking dependency — no new infrastructure beyond what's already in the
stack.

**Consequences:** `tests/integration/test_alert_evaluation_service.py::TestCooldownDeduplication`
directly proves both properties: a still-true condition evaluated twice in a row produces exactly
one `AlertEvent`, and running the same evaluation cycle five times in a row (simulating what
concurrent workers hitting the same alert would produce) still produces exactly one event. A
security with no computable data for its alert's type (no quote yet, insufficient history) is
counted as `skipped_no_data`, distinct from both a trigger and an error — never silently treated as
"condition not met" in a way indistinguishable from a real negative evaluation.

---

## ADR-040: A promotion gate makes `status` mean something — a model must beat its baseline (and not regress vs. the current PRODUCTION model) to ever be served

**Context:** Auditing the pre-Phase-10 registry for Phase 10's "model registry hardening" and
"model evaluation gates" requirements surfaced a real, pre-existing gap: `ModelRegistry` already
had a `status` field (`TRAINING`/`VALIDATED`/`STAGING`/`PRODUCTION`/`ARCHIVED`/`FAILED`) and
`ml.pipelines.train_pipeline.run_experiment` already set every trained model's status to
`VALIDATED` — but `ml.inference.serving.load_forecast_models` called `ModelRegistry.best_by_metric`
with **no status filter at all**, so the best-scoring record of a given `model_type` was served
regardless of its status. "Training succeeded" and "eligible to be served" were the same condition
in practice; `status` was decorative.

**Decision:** `ml.registry.promotion` (new) evaluates every gated candidate (`xgboost_return`,
`xgboost_direction`, `lstm_return`, `gru_return` — see `GATE_POLICY`) against the best registered
baseline of the matching type **on the same `dataset_version`** (apples-to-apples; a baseline
scored on different data proves nothing) and, if it beats that baseline, against whatever is
currently `PRODUCTION` for that `model_type` (a candidate that beats the baseline but regresses
against the currently-serving model is still rejected — the active model stays active).
`apply_promotion` mutates the registry accordingly: a passing candidate becomes `PRODUCTION`
(archiving whatever `PRODUCTION` record it replaces — `ModelRegistry.get_active` enforces at most
one `PRODUCTION` record per `model_type` and raises if that invariant is ever violated), a failing
one becomes `FAILED`. `train_pipeline.run_experiment` now calls this automatically for every gated
candidate right after registering it, so a trained model's real world state is always exactly one
of `PRODUCTION`/`FAILED` — never left sitting at `VALIDATED` (undecided) indefinitely.
`load_forecast_models` now calls `ModelRegistry.get_active` instead of `best_by_metric`, and raises
a clean `ModelUnavailableError` — a real, expected state, not a crash — if nothing has been
promoted yet for a required `model_type`.

This is explicitly **not** a profitability threshold or an arbitrary metric cutoff invented to make
training "pass" — it is model-vs-baseline and model-vs-current-production comparison only, using
metrics the training pipeline already computes, per this phase's own explicit instruction not to
force profitable-looking results.

**Real result on this project's actual bundled dataset** (`ml/experiments/registry.json`,
retroactively re-evaluated under the new gate): `xgboost_return` genuinely beats
`previous_return_baseline` on MAE (0.02243 → 0.02033) and was promoted; `xgboost_direction`
genuinely beats `majority_class_baseline` on f1_macro (0.242 → 0.290) and was promoted;
**`lstm_return` and `gru_return` do NOT beat `previous_return_baseline`** on this dataset (MAE
0.0258 and 0.0277 respectively, both worse than the baseline's 0.0224) and were correctly rejected
to `FAILED` — a genuine, honest finding this gate exists specifically to catch, not a fabricated
pass for either model.

**Model artifact integrity**: `ModelRecord` now also carries `artifact_checksum` (SHA-256 over the
artifact directory's files, computed generically across model types — XGBoost's `model.json`
vs. LSTM/GRU's `weights.pt`/`scaler.npz`/`config.json` — by hashing whatever files are actually
present, sorted by name) and `status_reason` (why the current status was set — a promoted model
records what it beat; a rejected one records what it failed to beat). `load_forecast_models` calls
`ModelRegistry.verify_artifact_integrity` before loading either `PRODUCTION` model and refuses to
serve a model whose on-disk artifact no longer matches its registered checksum (a corrupted or
tampered artifact) — treating a model artifact as an untrusted, verifiable file per this phase's
model-artifact-security requirement, not an implicitly-trusted one.

**Consequences:** `ml/tests/unit/test_promotion.py` and `ml/tests/unit/test_registry.py` cover the
gate/registry logic in isolation (promoted/rejected/regression/no-baseline/no-policy/artifact-
tampering cases); `ml/tests/integration/test_train_pipeline_integration.py::TestPromotionGateRunsAutomatically`
proves the gate actually runs as part of a real training run and that `get_active` and the registry
file agree on the outcome either way. `backend/tests/integration/test_alert_evaluation_service.py`'s
`FORECAST_CLASS_CHANGE` tests are skip-gated on a real `PRODUCTION` model existing (mirroring
`test_forecast.py`'s established `_REGISTRY_EXISTS` pattern, made one level more precise: a registry
file existing no longer implies a servable model exists).

## ADR-041: Prediction logging + live performance monitoring, kept structurally separate from training/backtest metrics

**Context:** Phase 10 required closing the PREDICTION → FUTURE OBSERVATION → REALIZED OUTCOME →
ERROR/PERFORMANCE loop — nothing before this phase persisted what a served forecast actually
predicted, so there was no way to later ask "was this model actually right, in production, over
time" as opposed to "what did it score on its held-out test set at training time."

**Decision:** A new `predictions` table (`app/db/models/prediction.py`) logs one row per real
forecast served — `forecast_service.get_forecast` calls `prediction_service.log_prediction` once
for the return model and once for the direction model (each carries its own `model_version`, since
the two models can be promoted independently) — never for the screener's separate in-memory
forecast reuse, which would massively over-count how many times a prediction was actually "made."
`realized_return`/`realized_direction`/`evaluated_at` stay `NULL` until
`prediction_service.evaluate_matured_predictions` (run daily via Celery Beat,
`app/workers/tasks/predictions.py`) confirms — using real subsequent `PriceBar` rows, counted as
actual trading-day rows after `as_of_date`, never a calendar-day approximation — that the
prediction's horizon has actually elapsed. `get_live_performance` computes MAE/RMSE (return
predictions) and a directional hit rate (Bullish/Bearish predictions only — Neutral makes no
directional claim and is excluded from that rate, never scored as a fabricated hit or miss) from
matured predictions only, with an explicit `insufficient_data` state when none exist yet.

This is **structurally never mixed** with `ml.registry`'s stored training/backtest metrics or
`backtest_service`'s output — they measure different things (held-out-test-set performance at
training time vs. this deployment's own real-world serving track record) and there is no shared
code path between `prediction_service.py` and either of those that could accidentally conflate
them; `LivePerformanceReport.disclaimer` states the distinction on every response.

**Consequences:** `tests/integration/test_prediction_service.py` proves the full loop against real
ingested price data: an unmatured prediction is never scored, a matured one is scored against the
exact real future bar (checked against an independently-computed expected value, not a hardcoded
number), and running evaluation twice in a row never double-scores the same prediction (the second
pass finds nothing left `evaluated_at IS NULL`). One real bug this session's own testing caught:
`evaluate_matured_predictions` originally never called `db.flush()` after `mark_evaluated`, so a
second query within the same session/transaction (including a second evaluation pass without an
intervening commit) couldn't see the just-written `realized_*` fields and would re-select the same
prediction as still-unevaluated — fixed by flushing immediately after each row is marked evaluated.

## ADR-042: Feature drift monitoring is PSI + mean-shift on already-existing indicators — a monitoring signal, never an automatic verdict

**Context:** Phase 10 asked for "practical" drift monitoring, explicitly warning against an
unnecessarily complex statistical framework, and explicitly requiring that a drift signal never by
itself mean a model has become invalid.

**Decision:** `app/services/drift_service.py` computes Population Stability Index (a standard,
widely-used credit-risk/ML-monitoring metric — not invented here) and a mean-shift-in-standard-
deviations for four features already surfaced elsewhere in this codebase (`rsi_14`, `sma_20`,
`volatility_20d`, `relative_volume_20` — the same indicators `get_technical_indicators`/the screener
already compute), comparing an earlier baseline window against a later current window of the SAME
security's own real price history (chronologically split, never randomly — a random split would
leak "current" rows into "baseline" and vice versa). Conventional PSI bands (< 0.1 none, 0.1-0.25
moderate, ≥ 0.25 significant) and a 2-standard-deviation mean-shift threshold classify severity —
both are standard reference thresholds, not tuned to produce a particular outcome. A report is a
`DriftReport(feature, metric, value, baseline_period, current_period, severity, timestamp)` — it is
returned to a caller (currently `GET /models/drift/{ticker}`, ANALYST/ADMIN) and never mutates
anything, blocks serving, or feeds back into the promotion gate; a human decides what to do with a
"significant" reading, exactly per this phase's "monitoring signal, not a verdict" requirement.

**Consequences:** `tests/integration/test_drift_service.py` proves the windows are chronologically
disjoint (baseline strictly precedes current), the computation is deterministic (same real data in,
same numbers out across repeated calls), and a security with too little history returns an empty
report rather than a fabricated one.

## ADR-043: Celery hardening — `acks_late` + reject-on-worker-lost + single-prefetch + task time limits, no new queueing system

**Context:** Phase 10's Celery/Redis hardening requirements (retries, timeouts, worker concurrency,
dead tasks, duplicate-execution safety) needed a real audit of `app/workers/celery_app.py`'s
existing configuration, not just new tasks bolted on top of unreviewed defaults.

**Decision:** `task_acks_late=True` + `task_reject_on_worker_lost=True`: a task is only acknowledged
once it finishes, and a worker process dying mid-task gets that task redelivered rather than
silently dropped. This is safe specifically *because* every task in this codebase was already (or
is now) idempotent under redelivery — market-data ingestion upserts by `(security_id, ts)`, alert
evaluation is guarded by a `SELECT ... FOR UPDATE` row lock plus cooldown (ADR-039), portfolio
transactions require an idempotency key, and prediction evaluation only ever touches rows still
`evaluated_at IS NULL` (a redelivered/re-run evaluation naturally does nothing to an already-scored
row — see ADR-041's consequences for the one real bug this property caught).
`worker_prefetch_multiplicity=1`: one task at a time per worker process, so a long `models.retrain`
run can never block that same worker from also picking up short, latency-sensitive tasks
(alerts/ingestion) queued behind it — horizontal parallelism comes from running more worker
*processes* (`--concurrency`), not a larger prefetch buffer. `task_time_limit=1800`/
`task_soft_time_limit=1700`: a hard ceiling generous enough to comfortably cover retraining (this
deployment's slowest task by a wide margin) while guaranteeing a genuinely stuck task (e.g. a hung
future real-market-data-vendor call) can no longer occupy a worker forever. `models.retrain` is
deliberately **not** on the Beat schedule — it is a manual/administrative trigger only
(`POST /models/retrain`), since it is compute-heavy with no natural fixed cadence this deployment
needs yet; automatic retry-on-failure is deliberately not configured for it either, since a failed
retraining run needs a human to look at why, not a silent retry loop.

**Consequences:** No new queueing system, broker, or scheduler — only PostgreSQL + Redis + Celery,
already present. `tests/integration/test_prediction_service.py`'s
`test_running_evaluation_twice_never_double_scores_the_same_prediction` and
`tests/integration/test_alert_evaluation_service.py`'s cooldown-deduplication tests are the concrete
proof that redelivery-safety holds, standing in for an actual worker-crash-mid-task scenario that's
impractical to simulate directly in a test.

## ADR-044: Multi-stage, non-root Docker images; dev/production stages instead of one shared image

**Context:** Auditing `backend/Dockerfile` for Phase 10's "Docker productionization" requirements
found it installed `requirements-dev.txt` (pytest/ruff/black/mypy/faker — none of which are needed
to run the application) into the same single-stage image actually deployed, ran as root, and had no
`.dockerignore` at all — which a real build attempt during this phase's own E2E validation exposed
concretely: the multi-gigabyte local `.venv` (torch/xgboost/pandas/etc., created during this
session's own testing) was being sent as Docker build context, making a build that should take
seconds take long enough to become impractical.

**Decision:** `backend/.dockerignore`/`frontend/.dockerignore` added (excluding `.venv`,
`__pycache__`, test-cache directories, `node_modules`, `.git`) — this alone fixed the build-context
bloat and benefits every future build regardless of the stages below. `backend/Dockerfile` becomes
three stages: `deps` (installs `requirements.txt` only, with the `gcc`/`libpq-dev` build tools this
needs — never reaching later stages), `dev` (adds `requirements-dev.txt` on top of `deps`; this is
what `infra/docker-compose.yml`'s `backend`/`worker`/`beat` services now explicitly target via
`target: dev`, preserving the existing bind-mount + `--reload` local workflow unchanged), and
`production` (built from `deps` only — no compilers, no dev/test tooling, a non-root `appuser`,
`docker build`'s default target since it's the last stage). The frontend already had an equivalent
`base`/`build`/`production` split from an earlier phase; only the backend needed this treatment.

**Consequences:** `.github/workflows/docker-build.yml` now builds each service's default (last,
i.e. production) stage and scans it with Trivy (`HIGH`/`CRITICAL`, known-fixable findings only —
scanning fails the build only on something an update would actually resolve, not on every
unfixable base-image CVE, which would train everyone to ignore the check). The production backend
image ships no pytest/ruff/mypy/faker and never runs as root.

## ADR-045: Production configuration fails fast at startup, not silently at request time

**Context:** Phase 10 required that production "fail safely when required secrets/configuration
are missing" — before this phase, `Settings` had no validation at all: a deployment with
`ENVIRONMENT=production` and the still-default `JWT_SECRET`/insecure cookie/localhost CORS origin
would start up and serve traffic exactly as if it were correctly configured, silently insecure.

**Decision:** `app/core/config.py::validate_production_config` runs once, inside `get_settings()`
(so it fires at the first settings access — practically, at process/app startup), and only when
`ENVIRONMENT == "production"` — every other environment (`development`/`test`/anything else) is
untouched, so this adds zero friction to local dev or CI. It checks: `JWT_SECRET` isn't the
development default, `DATABASE_URL` doesn't contain the development default password,
`COOKIE_SECURE` is `true`, and `CORS_ORIGINS` doesn't still include a wildcard or a localhost dev
origin. Any violation raises `InsecureProductionConfigError` (a `RuntimeError`) listing every
problem found at once, not just the first — refusing to start is safer than starting anyway and
silently running production traffic over a known-insecure configuration.

**Deliberately not a problem**: `DEMO_MODE=true` in production. A publicly-hosted demonstration of
this architecture using the synthetic demo provider, clearly labeled as such throughout the API/UI
(see ADR-007), is a legitimate production deployment shape for a portfolio project like this one —
never forced to `DEMO_MODE=false` just because `ENVIRONMENT=production`.

**Consequences:** `tests/unit/test_production_config_safety.py` constructs `Settings` directly
(never touching the process's actual environment) and covers every check independently, both the
insecure-value-is-rejected direction and the secure-value-passes direction, plus confirming
non-production environments are never validated at all.

---

## ADR-046: Real data provider ecosystem — config-driven selection independent of `demo_mode`, provenance-first storage, and three genuinely-evaluated (not assumed) provider integrations

**Context:** Phase 10's continuation required extending AlphaLens's existing `MarketDataProvider`/
`NewsProvider` abstractions to cover fundamentals and macro data, using `public-apis/public-apis`
as a discovery catalog only (never a runtime dependency), and to only integrate a provider after a
real evaluation of relevance, reliability, licensing, rate limits, and production suitability —
explicitly forbidding selecting something "because it appeared in a list." Every candidate below
was checked against its own official documentation/terms via live web fetches in this session, not
recalled from training data, specifically because a training-data assumption about a vendor's free
tier turned out to be wrong (see the Twelve Data finding below).

**Decision — provider selection per category:**

- **Market data — Twelve Data selected, Alpha Vantage and Finnhub rejected.** Alpha Vantage's free
  tier is 25 requests/day, impractical for any real ingestion cycle. Finnhub's `/stock/candle`
  (historical OHLCV) moved to paid tiers — free keys get HTTP 403 on exactly the endpoint AlphaLens
  needs (confirmed via a real Finnhub GitHub issue, not assumed). Twelve Data's free tier gives
  800 requests/day and multi-decade daily OHLCV. **Licensing caveat, verified directly against
  `twelvedata.com/terms` (Section 2.3), not a third-party summary that claimed otherwise**: the
  free tier explicitly forbids commercial use and redistribution — acceptable for this project's
  own demo/personal deployment, NOT acceptable if this deployment were ever operated commercially
  without upgrading. No `TWELVE_DATA_API_KEY` is configured in this deployment, so
  `TwelveDataMarketDataProvider` is built and unit-tested against mocked responses only; no live
  call was made (see `app/providers/market_data/twelvedata.py`'s docstring).
- **Fundamentals — SEC EDGAR selected.** The only fundamentals candidate that needs **no API key at
  all** — only an identifying `User-Agent` header per SEC's fair-access policy (10 req/sec) — which
  made it the only provider genuinely live-testable in this session without fabricating a
  validation. A real live `WebFetch`/`httpx` call against
  `data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json` confirmed the real response shape
  (`facts.us-gaap.<Concept>.units.<unit>[]`, each entry carrying `end`/`val`/`accn`/`fy`/`fp`/
  `form`/`filed`) before any parsing code was written against it. Data is public-domain XBRL,
  as-filed — `SECEdgarFundamentalsProvider` never converts a fact into a derived metric (P/E,
  growth, valuation); that needs a price and a documented methodology, deliberately deferred.
- **Macro — FRED selected.** Free, public-domain, authoritative (Federal Reserve Bank of St.
  Louis), and its `realtime_start` field maps directly onto the release-vs-observation-date
  distinction this phase required. No `FRED_API_KEY` is configured in this deployment (FRED
  requires a free registered key this session does not have) — `FREDMacroProvider` is built and
  unit-tested against mocked responses only; no live call was made.
- **News — no real provider integrated; Demo Mode preserved.** NewsAPI.org's free tier is
  explicitly localhost-only and forbids commercial use (disqualifying). Marketaux looked genuinely
  promising (finance-specific, entity-tagged, ~100 req/day free) but its Terms of Use page returned
  HTTP 403 to this session's fetch tool and could not be independently verified — **deliberately
  left unimplemented rather than integrated against licensing terms that could not be confirmed**,
  per this phase's explicit "do not blindly integrate" instruction. `DemoNewsProvider` remains the
  only registered news provider; `NEWS_PROVIDER=demo` is the only implemented value.

**Decision — architecture:** `FundamentalsProvider`/`MacroDataProvider` (new ABCs in
`app/providers/base.py`) mirror the existing `MarketDataProvider`/`NewsProvider` pattern — a small
provenance-rich dataclass per fact/observation (`FundamentalFact`/`MacroObservationData`), never a
computed metric baked into the provider layer. A shared `app/providers/http_client.py` gives every
real adapter (SEC EDGAR, Twelve Data, FRED) the same bounded retry/backoff policy: a timeout gets a
bounded retry, a 429 respects `Retry-After` within a bounded retry count, a 5xx retries then raises
`ProviderUnavailableError`, any other 4xx fails immediately with zero retries, and malformed JSON on
a 200 raises `ProviderResponseError` — nothing here ever fabricates a fallback value or silently
replaces missing data with zero (`FREDMacroProvider` in particular preserves FRED's `"."`
no-data sentinel as `None`, never `0`).

Provider *selection* is now independent of the pre-existing `demo_mode: bool` (which remains, and
still gates the unrelated email-provider registry): four new settings —
`market_data_provider`/`news_provider`/`fundamentals_provider`/`macro_provider` (plus an
informational `data_environment`) — each default to a safe, credential-free value (`"demo"` or
`"none"`) so a fresh checkout runs in Demo Mode with nothing configured. `get_market_data_provider`/
`get_news_provider` were changed to branch on their own setting instead of `demo_mode`; grepping
every `demo_mode` usage first confirmed only two real branch points existed and no test asserted on
the old `demo_mode=False → NotImplementedError` behavior, so this was a deliberate, tested behavior
change, not a silent one.

**Decision — storage & provenance:** `fundamentals` and `macro_observations` are new, structured
tables (real numeric/date columns, not JSONB blobs, so concept/period queries work) — never merged
into `PriceBar`, which has different provenance and freshness semantics. Both are idempotent on a
natural identity (`uq_fundamentals_identity` on `security_id, concept, unit, period_end,
fiscal_period, form`; `uq_macro_observations_identity` on `series_id, observation_date`) via
`ON CONFLICT DO UPDATE`, matching `PriceBarRepository.upsert_many`'s established pattern. Macro
observations are stored independently of any security per the phase's explicit requirement — no FK
to `securities` — and retain a `vintage_date` (FRED's `realtime_start`) separately from
`observation_date` specifically so `MacroRepository.get_as_of(series_id, as_of=...)` can answer
"what was known as of this timestamp," not "what does this observation date say now" — the
no-look-ahead-bias lookup a later feature-engineering join must use instead of a naive join on
`observation_date` alone (covered by `tests/integration/test_macro_repository.py::TestGetAsOfNoLookAheadBias`).
The macro table deliberately does **not** retain full revision history (a later-revised GDP figure
overwrites the prior value for the same `observation_date`) — a documented simplification, not an
oversight; only the latest known value and the vintage it was known as of are kept.

**Decision — provider health & agent integration:** `GET /api/v1/system/providers`
(ANALYST/ADMIN-only, mirroring `GET /models`) reuses the existing `jobs` table for last-success/
last-failure per category rather than adding a new tracking table — no new infrastructure. It
reports which provider is configured per category and whether a required credential is present as
a boolean, **never the credential's value**. Three new read-only agent tools
(`get_fundamentals`, `get_macro_indicators`, `get_data_source_status`) follow the exact pattern
every existing tool already follows (Pydantic input, deterministic service call, structured output
+ `Evidence`, `available: false` with **no evidence entry** rather than a fabricated one when
nothing has been ingested) — no new tool category, no LLM-computed financial metric, no
`execute_sql`/`execute_python`/shell escape hatch.

**Consequences:** `tests/unit/test_provider_http_client.py` (9 tests) covers the shared retry
policy; `tests/unit/test_sec_edgar_provider.py`, `test_fred_provider.py`,
`test_twelvedata_provider.py` (24 tests total) cover each real adapter against mocked HTTP —
request construction, response parsing, auth validation, malformed-response handling, and each
provider's specific real-world quirk (Twelve Data's 200-with-error-body convention; FRED's `"."`
sentinel; SEC's per-entry malformed-data tolerance). `tests/integration/test_sec_edgar_live.py` is
the one genuine `@pytest.mark.live_provider` live test — excluded from the default `pytest` run via
`addopts = "-m 'not live_provider'"` in `pyproject.toml` (SEC EDGAR needs no credential to
`skipif`-gate on the way `live_llm` tests do, so an explicit marker exclusion was required to keep
the default suite offline) and was actually run once in this session against the real
`data.sec.gov` API, passing genuinely (2/2, ~12s of real network round trips). Repository/service/
API tests for fundamentals and macro (idempotency, provenance, `available: false` semantics,
role-gated provider-status endpoint) bring the total new/changed test count for this continuation
to 65 backend tests, all passing alongside the full pre-existing suite with zero regressions.

## ADR-047: Phase 10 finalization audit — a duplicate-delivery guard for retraining, and skipped-record visibility for fundamentals/macro parsing

**Context:** A finalization audit of the whole Phase 10 MLOps stack (registry, promotion,
retraining, prediction logging, monitoring, drift, health/readiness, Celery/Redis, CI/CD, security)
found the existing implementation intact and passing — no component needed rebuilding. Two genuine,
narrow gaps surfaced from explicitly auditing "retry behavior and idempotency" (Celery) and "never
silently hide a large number of rejected records" (data quality).

**Decision — retraining duplicate-delivery guard:** `celery_app.py`'s `task_acks_late=True`
(ADR-043) means Celery can redeliver the same task message at least once. Unlike market-data
ingestion (idempotent via `ON CONFLICT DO UPDATE`) or alert evaluation (already row-locked,
ADR-039), `retraining_service.run_retraining` had no protection against a redelivered duplicate
re-running the same multi-minute training experiment a second time — a real risk because
`ml.registry.registry` persists to `registry.json` via a plain, unlocked `write_text()` call, so two
concurrent runs could race and lose one's update. `JobRepository.get_by_id_locked` (new — `SELECT
... FOR UPDATE`) plus a `status != QUEUED` guard at the top of `run_retraining` makes a redelivered
duplicate a clean no-op, mirroring `alert_evaluation_service`'s established row-lock pattern rather
than introducing a new locking primitive. This does **not** guard against two genuinely separate
`POST /models/retrain` calls running concurrently (different `job_id`s) — accepted as a limitation
for this manual, administrative-only, rarely-concurrent endpoint rather than justifying a new
distributed lock (Redis-based or otherwise) for it. Covered by
`tests/integration/test_retraining_service.py` (6 tests, `run_experiment` monkeypatched — never a
real multi-minute run in the normal suite).

**Decision — skipped-record visibility:** `SECEdgarFundamentalsProvider.get_company_facts` and
`FREDMacroProvider.get_observations` each silently dropped an individual malformed entry (by
design — one bad data point shouldn't fail the whole response) but surfaced no count anywhere,
meaning a real, large parse-failure rate (a schema change, say) would have been invisible. Both now
log a structured warning (`sec_edgar_entries_skipped` / `fred_observations_skipped`) with
seen/parsed/skipped counts whenever any entry is dropped — no change to either method's return
contract (`CompanyFactsResult`/`list[MacroObservationData]` unchanged), so this is purely additive
observability, not a rebuild of the existing "reject malformed, never fabricate" parsing behavior.

**Consequences:** Both fixes are small, additive, and reuse an existing pattern rather than new
infrastructure. 6 new backend tests (`test_retraining_service.py`); the existing SEC EDGAR/FRED
mocked unit tests continue to pass unchanged (517 total backend tests: 511 passed, 22
correctly-skipped live-LLM, 2 explicitly-gated live-provider — 0 regressions).

**A real infrastructure incident during this audit, unrelated to any code change**: attempting the
mandated Docker production-build validation, an initial `docker build` attempt was cancelled
client-side (via the harness) after appearing stuck under severe host-disk I/O pressure (the host
`C:` drive was already down to single-digit GB free from Docker Desktop's 90+GB WSL VHDX — see this
document's Phase 10 continuation notes). The cancelled client process did not stop the build
server-side; BuildKit kept writing inside Docker's VM and the host disk collapsed to 0 bytes free a
second time this project. Recovery required forcibly terminating Docker Desktop's WSL distro
(`wsl --terminate docker-desktop`, which also stopped the user's unrelated running project's
containers — they came back on their own via their `restart: unless-stopped` policy once Docker's
engine recovered) plus clearing several hundred MB of genuinely disposable Windows/Docker updater
temp files (`%LOCALAPPDATA%\Temp`) to restore a stable ~4.3GB free. **No Docker image was
successfully built during this finalization pass** — see the final report's Docker/known-limitations
sections for what was validated instead (`docker compose config`, `.dockerignore` audit, the
already-existing images from a prior successful build).

## ADR-048: Phase 10.5 — Product UI & Intelligence Experience

**Context:** The backend/ML system substantially outgrew the frontend — real SHAP
explainability, a 27-feature technical model, provider health, alert event history, and
portfolio performance history all existed in the API but were invisible or under-surfaced in
the UI. This phase rebuilt the frontend as a dense analytical interface over the *existing*
system — no new backend capability, no new infrastructure, no fabricated data anywhere.

**What changed (frontend, by page):**
- **Shell**: real global ticker/company search (`GET /stocks?q=`), a real alerts-triggered-in-24h
  indicator (derived from `last_triggered_at`, not an invented "unread" count).
- **Design system**: `DataTable`, `MetricCard`, `PageHeader`/`SectionHeader`, `StatusBadge`,
  `SignalBadge`, `Tabs`, `ChartContainer`, `EvidenceCard`, `Tooltip` — replacing five pages'
  worth of duplicated hand-rolled `<table>` markup and four duplicated percent/money formatters
  (centralized into `lib/format.ts`).
- **Dashboard**: restructured into a two-column layout; added an "AI Signals" panel — real
  per-ticker XGBoost forecasts for the day's visible movers (bounded to 8 tickers), never a
  fabricated market-wide "opportunity score".
- **Stock Detail**: tabbed (Overview/AI Forecast/Technicals/News & Sentiment). The SHAP
  "why this prediction" view is now a real horizontal contribution-bar chart (signed, from the
  backend's actual TreeExplainer output). New **Technicals** tab requests the forecast
  explanation at `top_n=27` (all features) instead of the default 5, so it shows real values for
  a curated technical-indicator subset (RSI, momentum, volatility, MACD, ATR, Bollinger %B,
  relative volume) with their real SHAP-direction pull — never an invented "Trend: Positive"
  interpretation the backend doesn't itself assert. Added a watchlist quick-add and a
  create-alert shortcut to the header.
- **Screener**: exposed `min/max_change_percent` and `min/max_return_20d_percent` filters —
  these were already accepted by the backend (`app/api/v1/screener.py`) but the frontend's
  `ScreenerFilters` type and `runScreener()` never forwarded them, so the filter fields would
  have been dead UI without also fixing `screener/types.ts` and `screener/api.ts`. Sorting is
  now backend-driven (`sort_by`/`sort_direction` query params via `DataTable`'s sortable
  headers), not a client-side re-sort of one page of results.
- **Watchlists**: detail view adds a real per-ticker AI Signal column, bounded to watchlists of
  ≤15 items (one extra `/forecast` call per row — the backend's watchlist-detail endpoint
  batches quotes only, not forecast/sentiment, a documented Phase 9 scope decision in
  `watchlist_service.py`); above that size the column is omitted with an honest note rather than
  issuing an unbounded number of requests.
- **Portfolio**: added a real portfolio-value-over-time chart (`GET .../performance`, previously
  fetched but never visualized) and an allocation breakdown by holding market value — both
  correctly exclude/flag data points or holdings with an unavailable price rather than treating
  a missing value as zero.
- **Alerts**: added a per-alert "recent events" expansion using `GET /alerts/:id/events`, an
  endpoint that existed but was never called anywhere in the UI — alerts previously only showed
  `last_triggered_at`, never the actual triggering `message`/`observed_value` history.
- **Backtest**: added a drawdown chart, computed client-side from the response's own
  `equity_curve` (a standard, deterministic peak-to-trough transformation of real data, not a
  new series the backend invented) since the API returns only a scalar `max_drawdown`, no
  discrete drawdown series. Added an "Execution Assumptions" card echoing the response's own
  `commission_bps`/`slippage_bps`/`initial_capital`.
- **Research Assistant**: root-caused the permanent "unavailable" state to a genuine environment
  condition — `get_llm_provider()` requires `LLM_API_KEY`/`GROQ_API_KEY`/`GEMINI_API_KEY`, none
  configured. The existing `FakeLLMProvider` is scripted with a *finite* response queue for unit
  tests; wiring it into the live chat path was considered and rejected — a real user's freeform
  questions would get canned, unrelated answers and then a hard failure once the queue was
  exhausted, which is materially the "fake chatbot" this phase explicitly forbids, not a
  legitimate use of the existing test double. Instead: the unavailable state now surfaces the
  backend's real, actionable error detail (which env var to set) alongside the existing stable
  summary sentence; a genuine rate-limit (429) is now visually and textually distinct from a
  true unavailability; suggested prompts were added, each verified against `app/agent/tools.py`
  to correspond to a real tool; evidence rendering was upgraded to the shared, expandable
  `EvidenceCard`; and real per-tool-call activity (`tool_calls`, name/success/latency) is now
  shown on grounded answers.
- **Provider/model visibility**: a compact `ProviderStatusPanel` on the Dashboard, visible only
  to ANALYST/ADMIN (matching `GET /system/providers`' own RBAC — the panel issues no request at
  all for a plain `USER`, rather than firing a request that would 403). Status is derived purely
  from the response's own fields (`configured_provider`, credential/success/failure timestamps)
  — never a fabricated health check.

**A real backend bug found and fixed along the way:** `app/main.py` registered slowapi's default
`RateLimitExceeded` handler explicitly, which returns `{"error": "<plain string>"}` — breaking
the app's own `{"error": {"code", "message"}}` envelope that every other endpoint (and the
frontend's `api-client.ts` error parsing) depends on. Since `RateLimitExceeded` already
subclasses Starlette's `HTTPException`, removing that explicit registration lets it fall through
to the existing generic `HTTPException` handler, which wraps it correctly with the real
rate-limit detail intact. This affected every rate-limited endpoint, not just
`/research/chat` — previously any 429 anywhere in the app silently degraded to a generic
`UNKNOWN_ERROR` with no message on the client. Covered by a strengthened assertion in the
existing `test_rate_limit_is_enforced` (`tests/api/test_research_chat.py`), and confirmed via
the full 511-test backend suite with zero other regressions.

**Consequences:** 99 frontend tests (up from 74), 20 test files (up from 17) — two new test
files (`WatchlistDetailPage.test.tsx`, `PortfolioDetailPage.test.tsx`; previously untested) plus
new coverage on every changed page. No new dependencies, no new infrastructure, no database
migrations. `formatMoney` for portfolio/backtest values now explicitly pins `Intl.NumberFormat`
to `"en-US"` — a real, test-caught bug was found where `Number.prototype.toLocaleString()`
without an explicit locale silently used the runtime's default locale, rendering
`$100,000` as `$1,00,000` (Indian digit grouping) in this environment.
