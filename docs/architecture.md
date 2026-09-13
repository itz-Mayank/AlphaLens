# Architecture

## Status

Reflects Phase 8.5 (multi-provider live LLM validation) as implemented. Updated at the end of each
phase. `ml/` is a fully-implemented, standalone package (data validation, features, targets,
datasets, models, evaluation, registry, inference, explainability, backtest, nlp) — see
[ml-pipeline.md](ml-pipeline.md) for the full data contract and methodology. It is wired into
`backend/` for inference, backtesting, and sentiment only (`app/services/forecast_service.py`,
`backtest_service.py`, `news_sentiment_service.py`) — never for training (ADR-001). Phase 8 adds a
grounded LLM research agent (`app/agent/`) that reasons over this same deterministic data through a
fixed set of controlled tools; the LLM itself never touches the database, computes a metric, or
trains anything — see "Research agent flow" below. Phase 8.5 adds two more real `LLMProvider`
implementations (Groq, Gemini) behind the same abstraction, selected via `LLM_PROVIDER` — the
orchestrator, tools, evidence model, and every other Phase 8 guarantee are unchanged and provider-
agnostic by construction.

## Component overview

```
┌────────────┐      HTTP        ┌──────────────┐
│  Frontend  │ ────────────────▶│   Backend    │
│ React/Vite │ ◀────────────────│   FastAPI    │
└────────────┘                  └──────┬───────┘
                                        │
                   ┌────────────────────┼────────────────────┐
                   ▼                    ▼                     │
            ┌─────────────┐     ┌──────────────┐              │
            │ PostgreSQL  │     │    Redis     │              │
            │ (system of  │     │ DB0: GET     │              │
            │  record)    │     │  cache (TTL) │              │
            │             │     │ DB1: Celery  │              │
            │             │     │  broker      │              │
            │             │     │ DB2: Celery  │              │
            │             │     │  result      │              │
            └──────▲──────┘     │  backend     │              │
                   │            └──────┬───────┘              │
                   │                   │                      │
                   │            ┌──────▼───────┐   .delay()   │
                   │            │ Celery        │◀────────────┘
                   │            │ worker        │
                   │            │ (market_data. │
                   │            │  ingest,      │
                   │            │  news.ingest) │
                   │            └──────┬────────┘
                   └───────────────────┘
                     own DB session,
                     separate connection
                     from the API request
                     that enqueued it
```

There is one Celery task today (`market_data.ingest`); the worker/broker/result-backend wiring is
generic and later phases (training, backtests, news processing, alerts, reports) add tasks to the
same worker rather than standing up new infrastructure — see ADR-009 for the matching "one
generic `jobs` table" decision. Redis's three logical DBs (cache, broker, result backend) are
separate `REDIS_URL`/`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` connections against the same
Redis instance, not three instances.

## Package boundaries

- **`backend/`** — FastAPI app: routing, auth, request validation, persistence, orchestration.
  Imports `ml.inference`/`ml.explainability`/`ml.backtest`/`ml.nlp` for synchronous forecast/
  explanation/backtest/sentiment serving (`app/services/forecast_service.py`, `backtest_service.py`,
  `news_sentiment_service.py`, `ml_common.py`); never imports `ml.training` or `ml.pipelines`, and
  no route handler ever trains anything (ADR-001). `ml/` is installed into the backend's own venv
  as an editable local package (ADR-021) — `import ml` works from `backend/` the same way in local
  dev and in Docker (`pip install -e /ml` at container start, since `/ml` is only populated once
  the bind mount below is live). `backend/requirements.txt` added `torch`/`transformers` in Phase 7
  for FinBERT (ADR-027, amending Phase 6's "no torch in the backend"). `app/providers/` holds
  provider ABCs, one per phase that needs one (`EmailProvider` — Phase 2; `MarketDataProvider` —
  Phase 3; `NewsProvider` — Phase 7), each with its own subpackage implementing a `DEMO_MODE`-backed
  registry function — see ADR-002 (amended). `app/workers/` holds the one Celery app
  (`celery_app.py`) and its tasks (`tasks/`); task modules are deliberately thin, delegating real
  logic to `app/services/` so that logic is unit-testable without Celery (proven by
  `app/services/market_data_service.py::run_ingestion` and `news_sentiment_service.py::run_news_ingestion`,
  both called directly by integration tests and wrapped by thin `app/workers/tasks/*.py` modules for
  the real worker path).
- **`ml/`** — Standalone Python package (own `pyproject.toml`/venv/requirements, no FastAPI
  dependency — verified by `grep`, nothing under `ml/ml/` imports `fastapi` or `backend`).
  `data/` (validation, research-data provider + provenance), `features/` (27 trailing-only
  technical features, `fs_v1`), `targets/` (return/direction target definitions), `datasets/`
  (chronological split, tabular + sequence dataset builders), `models/` (naive baselines, XGBoost,
  LSTM, GRU — one shared `Model` ABC), `evaluation/` (classification, regression, per-ticker
  financial-strategy metrics), `registry/` (JSON-file model registry), `inference/` (`inference.py`'s
  low-level `predict() -> PredictionResult`, `serving.py`'s Phase 6 orchestration layer —
  raw price history to a served prediction), `explainability/` (Phase 6: SHAP for XGBoost),
  `backtest/` (Phase 6: portfolio-level backtest engine, separate from `evaluation/`'s per-ticker
  metrics — ADR-024), `nlp/` (Phase 7: FinBERT financial sentiment, `ml.nlp.sentiment`),
  `pipelines/` (training orchestration, `run_experiment`). `ml/training/` remains an empty
  scaffold. Training runs via `ml/scripts/run_real_experiment.py` today, never inside an HTTP
  request; a future Celery task wrapping `ml.pipelines` would follow the identical thin-wrapper
  shape `market_data.ingest`/`news.ingest` established in Phases 3 and 7.
- **`frontend/`** — React SPA, feature-organized (`src/features/<domain>/`). Server state lives in
  TanStack Query; local/UI state (theme, etc.) lives in Zustand. No server data is duplicated into
  a Zustand store.
- **`app/agent/`** (Phase 8, extended in 8.5) — the research agent, isolated from every other
  package the same way `app/providers/` isolates provider ABCs: `llm_provider.py` (vendor-agnostic
  `LLMProvider` ABC with four implementations — real `AnthropicLLMProvider`, `GroqLLMProvider`,
  `GeminiLLMProvider`, and a deterministic `FakeLLMProvider` used by the entire test suite —
  ADR-029/034), `tools.py` (the fixed, closed set of 9 controlled tools — no
  `execute_sql`/`execute_python`/`execute_shell`/filesystem tool exists or ever will, ADR-030),
  `evidence.py` (the `Evidence`/citation-tag model), `prompts.py` (the versioned static system
  prompt), `conversation.py` (bounded, per-`(user_id, conversation_id)` in-memory turn history —
  ADR-032), and `orchestrator.py` (the bounded tool-calling loop — unchanged since Phase 8;
  provider-agnostic by construction, ADR-034). Every tool wraps an existing Phase 5-7 service/
  repository; `app/agent/` adds no new data access or calculation of its own.

## Request flow (current)

`GET /health` and `GET /ready` are implemented directly on the FastAPI app (not versioned under
`/api/v1`, since they're infrastructure probes, not product API). `/ready` performs a live
`SELECT 1` against Postgres. All product endpoints are added under `/api/v1`, each following
`route → service → repository → ORM model` (`app/api/v1/` → `app/services/` →
`app/repositories/` → `app/db/models/`). Every request gets one request-scoped SQLAlchemy session
(`app/db/session.py::get_db`) that commits on success and rolls back on any exception. Phase 2
added `/api/v1/auth/*` and `/api/v1/users/*`; Phase 3 added `/api/v1/stocks/*`,
`/api/v1/market-data/ingest`, and `/api/v1/jobs/{id}`; Phase 4 adds
`/api/v1/dashboard/overview` — see [api.md](api.md) for the full list.

`GET /stocks*` and `GET /dashboard/overview` read through a Redis cache (`app/core/cache.py`)
before hitting Postgres; `POST /market-data/ingest` is the one route so far that both writes
(`jobs` row) and enqueues a Celery task — see "Background-job flow" below for why it commits
before enqueueing rather than relying on `get_db`'s usual trailing commit.

## Auth flow (Phase 2)

Register/login issue a short-lived JWT access token (response body, held in memory client-side)
plus an opaque refresh token (`httpOnly` cookie, hashed at rest). `POST /auth/refresh` rotates the
refresh token on every use. `frontend/src/features/auth/useAuthBootstrap.ts` calls `/auth/refresh`
once on app load to silently restore a session from the cookie; `frontend/src/lib/api-client.ts`
retries any request that comes back `401` once, after a refresh, before giving up and clearing the
session. Full detail: [security.md](security.md) and ADR-005 in [decisions.md](decisions.md).

## Data flow (Phase 3: market data)

```
DemoMarketDataProvider (synthetic, seeded — real vendor plugs in later behind the same ABC)
        │  list_securities() / get_daily_bars(ticker, start, end)
        ▼
app/services/market_data_service.py::run_ingestion
        │  validates each bar (app/services/market_data_validation.py) — REJECTED
        │  bars (non-positive price, negative volume, invalid OHLC relationship,
        │  duplicate timestamp in batch, future-dated — Phase 10 added the last
        │  one) are dropped, never block the rest of the batch; WARNING-tier
        │  findings (Phase 10: an abnormal >50% day-over-day move) and gap
        │  detection are informational only, recorded in job metadata, never
        │  block ingestion — this module can't tell a genuine large move from a
        │  bad print, so it flags rather than guesses
        ▼
app/repositories/price_bar_repository.py::upsert_many
        │  INSERT ... ON CONFLICT (security_id, ts) DO UPDATE — idempotent by construction,
        │  not by a "check before insert" that could race
        ▼
PostgreSQL (securities, price_bars, jobs)
        │
        ▼
app/core/cache.py (30-60s TTL, ADR-010) ──▶ FastAPI (/stocks*) ──▶ React (Stock Explorer/Detail)
```

## Background-job flow (Phase 3)

`POST /market-data/ingest` (ANALYST/ADMIN only): creates a `jobs` row (status `QUEUED`), **commits
immediately** (not left to `get_db`'s trailing commit), then calls
`ingest_market_data_task.delay(...)`. The explicit early commit matters because the Celery worker
is a separate OS process with its own DB connection — without it, a worker that picks up the
message fast enough could look up the job before the API's transaction was visible to it (a real
dispatch-before-commit race, not a hypothetical one). The task
(`app/workers/tasks/market_data.py`) opens its own session, calls `run_ingestion`, and commits or
rolls back exactly like a request would. `run_ingestion` itself never raises past its own
boundary — any failure is caught and recorded as `jobs.status = 'FAILED'` with the error message,
so a broken provider or a bad ticker can't leave a job stuck at `RUNNING` forever.

`CELERY_TASK_ALWAYS_EAGER=true` (set in `.env.test` for a couple of narrow uses, not the default
test path) runs a task synchronously in the caller's process — useful for manual local testing
without a separate worker. It is *not* used to test `POST /market-data/ingest` end-to-end, because
eager mode would still create a second logical execution sharing nothing with the test's
transactional DB fixture; see `tests/api/test_market_data.py` (mocks `.delay()`, tests the HTTP
contract) versus `tests/integration/test_market_data_service.py` (calls `run_ingestion` directly,
same session, tests the real logic including idempotency) and
`tests/integration/test_ingestion_task.py` (a real separate connection, proving the Celery
wrapper's session lifecycle actually works end to end).

## News ingestion flow (Phase 7)

Same job/Celery shape as market-data ingestion above (`POST /news/ingest`, ANALYST/ADMIN only,
early commit before `.delay()`, thin task wrapper, failures recorded on the job row rather than
left `RUNNING` forever) — see "Background-job flow" for that mechanism. The domain-specific
pipeline inside `run_news_ingestion` (`app/services/news_sentiment_service.py`):

```
NewsProvider.fetch_articles(tickers, since, until, limit)
        │
        ▼
normalize → filter language → deduplicate
        │
        ▼
NewsRepository.upsert_articles()          -- idempotent: (source, external_id)
        │
        ├─ entity_extraction_service.extract_entities()   -- per article, vs. securities table
        │       → NewsRepository.add_entity_matches()      -- idempotent: (article_id, security_id)
        │
        └─ ml.nlp.sentiment.analyze_batch()  -- only articles missing this model_version's score
                → NewsRepository.upsert_sentiment()  -- idempotent: (article_id, model_version)
```

FinBERT inference is the CPU-heavy step here — the same reason training never runs inside an HTTP
request applies to this pipeline: `run_news_ingestion` only ever executes inside the Celery worker,
never inside `POST /news/ingest`'s request handler. See [ml-pipeline.md](ml-pipeline.md) "News &
sentiment pipeline" for the full methodology (provider abstraction, entity-mapping confidence
thresholds, temporal-leakage-free aggregation, idempotency guarantees).

Read paths (`GET /stocks/{ticker}/news`, `/sentiment`, `/sentiment/history`) are synchronous,
cached-free (no Redis caching added for these yet — the underlying data changes only when an
ingestion job runs, infrequently relative to a TTL-based cache's benefit) queries through
`app/services/news_query_service.py` + `news_sentiment_aggregation.py`.

## Dashboard aggregation flow (Phase 4)

```
GET /dashboard/overview
        │  (any authenticated role — read-only, no RBAC gate)
        ▼
app/core/cache.py  ──▶ cache hit (90s TTL) ──▶ return cached JSON
        │ miss
        ▼
app/services/dashboard_service.py::build_dashboard_overview
        │  1. SecurityRepository.count_all() / count_by_sector() / list_distinct_data_sources()
        │  2. PriceBarRepository.get_latest_quotes() — ONE window-function query for every
        │     tracked security's latest bar + its immediately preceding close (ADR-011),
        │     not one query per security
        │  3. filter to the shared reference date (ADR-012) for movers/sectors/breadth
        │  4. compute_return_percent — delegates to market_data_service.compute_price_change,
        │     the single canonical return formula (ADR-013)
        ▼
DashboardOverview (market_summary, market_movers, sector_overview, market_breadth,
                   recent_activity — every section has a defined "no data yet" shape)
```

Every figure traces back to `securities`/`price_bars` through this one path — nothing in the
dashboard response is computed differently than the equivalent figure on `/stocks/{ticker}`
(enforced by ADR-013, after a real cross-check caught a divergence during manual E2E testing).

## ML inference flow, training flow

Training flow (unchanged since Phase 5 — still never runs inside an HTTP request):

```
ml/scripts/run_real_experiment.py
        │
        ▼
ml.pipelines.train_pipeline.run_experiment(config, output_dir, provider)
        │
        ├─ SampleSP500ResearchProvider.load()  (real historical OHLCV + provenance)
        ├─ ml.data.validation.validate() / .clean()
        ├─ ml.features.pipeline.build_features()        (27 trailing-only features)
        ├─ ml.targets.targets.future_return() / classify_return()
        ├─ ml.datasets.temporal_split.chronological_split()   (train/validation/test, by date)
        ├─ ml.datasets.tabular / ml.datasets.sequences         (per-model dataset shape)
        ├─ train + evaluate: naive baselines, XGBoost, LSTM, GRU
        │        (ml.evaluation.classification/regression/financial)
        └─ write configuration.json / provenance.json / metrics.json / split_bounds.json /
           models/<name>/<artifact>, and register each model in ml.registry.ModelRegistry
```

See [ml-pipeline.md](ml-pipeline.md) for the full data contract, leakage-prevention rules, feature
list, target design, and real experiment results.

Inference/backtest flow (Phase 6, synchronous, never trains anything):

```
HTTP request                              HTTP request
GET /stocks/{ticker}/forecast             POST /research/backtest
        │                                          │
        ▼                                          ▼
app/services/forecast_service.py          app/services/backtest_service.py
        │                                          │
        ├─ SecurityRepository / PriceBarRepository (this deployment's own price_bars —
        │                                            demo data by default, see ADR-023)
        ├─ ml_common.load_models()      -- shared registry-backed model cache, both services
        │      -> ml.inference.serving.load_forecast_models(registry_path)
        ├─ ml.inference.serving.build_latest_feature_row() / generate_historical_predictions()
        │      -> the SAME ml.features.pipeline.build_features() training used
        ├─ ml.inference.inference.predict_return() / predict_direction()   (forecast_service)
        │  ml.explainability.shap_explainer (forecast_service, /forecast/explanation only)
        │  ml.backtest.engine.run_portfolio_backtest()                     (backtest_service)
        └─ ForecastResponse / ForecastExplanationResponse / BacktestResponse
           — every response carries data_source + a disclaimer, never hidden (ADR-023)
```

`ml_common.py`'s in-process model cache (keyed by registry path + file mtime) avoids re-reading
XGBoost artifacts from disk on every request while still picking up a new training run without a
restart. Every `ml.inference.serving.ServingError` (unknown/unsupported ticker, insufficient
history, failed validation, unavailable model) maps to a specific `AppError` subclass — a clean
4xx/5xx, never a raw stack trace (see [api.md](api.md) for the exact codes).

## Research agent flow (Phase 8, provider layer extended in 8.5)

```
User (frontend /app/research/chat)
        │  message + optional conversation_id
        ▼
POST /api/v1/research/chat  (rate-limited: 20/hour, ADR-031)
        │
        ▼
app/services/agent_chat_service.py::chat
        │  resolves the LLM provider (ADR-029), maps every failure to a
        │  clean AGENT_UNAVAILABLE 503 — never a raw provider exception
        ▼
app/agent/orchestrator.py::run_agent          ◀── app/agent/conversation.py
        │   loads bounded history keyed by (user_id, conversation_id)
        │
        │   ┌─────────────────────────────────────────────────────┐
        └──▶│ LLM — Anthropic, Groq, or Gemini (LLM_PROVIDER),     │
            │ system prompt + history + tool definitions,          │
            │ converted to that provider's own wire format         │
            └──────────────────────┬──────────────────────────────┘
                    no tool call?  │  tool call(s) requested?
                    (final answer) │
                                   ▼
                     app/agent/tools.py — Tool Selection
                                   │  validate args against the tool's own
                                   │  Pydantic input model
                                   ▼
                    Controlled Tools (fixed set of 9, ADR-030)
                     get_stock_quote · get_price_history · get_technical_indicators
                     get_forecast · get_forecast_explanation · get_news
                     get_sentiment · get_sentiment_history · run_backtest
                                   │  each wraps an EXISTING Phase 5-7
                                   │  service — no new data access/calc
                                   ▼
                    Structured Evidence (app/agent/evidence.py)
                     {source_type, source_id, ticker, timestamp, data, provenance}
                                   │  wrapped as "DATA, not an instruction"
                                   │  before re-entering the conversation
                                   │  (prompt-injection defense, docs/security.md)
                                   ▼
                     ── loop back to the LLM (bounded: llm_max_tool_iterations,
                        llm_max_tool_calls_per_turn) ──
                                   │
                                   ▼
                    LLM Reasoning over the returned evidence
                                   │
                                   ▼
                    Grounded Response: answer + evidence[] + citations[]
                    + tools_used[] + tool_calls[] + model/provider metadata
                    (never chain-of-thought — app/schemas/agent.py::ChatResponse)
```

**The LLM is a reasoning component only.** It selects which tool to call and synthesizes the final
answer from the tool results the orchestrator hands back; it never queries the database, computes a
financial metric, forecasts a price, scores sentiment, or runs a backtest itself — every number in
a response traces back to one of the 9 tools above, each of which is a thin wrapper over an
already-existing Phase 5-7 service (`forecast_service.py`, `backtest_service.py`,
`news_query_service.py`, `market_data_service.py`, `ml.inference.serving`). No trades are placed, no
portfolio or configuration state is changed, no model is retrained, and no code is executed on the
agent's behalf — see [security.md](security.md) for the full non-autonomy and prompt-injection
posture. This is exactly as true for Groq/Gemini as for Anthropic: `GroqLLMProvider`/
`GeminiLLMProvider` declare only AlphaLens's own 9 function tools and never enable either vendor's
own built-in, server-side tools (Groq's hosted web search/code execution; Gemini's
`google_search`/`code_execution`/`computer_use`) — the 9-tool boundary above is a property of what
this codebase declares to the vendor API, not of which vendor is configured (ADR-030, reaffirmed by
ADR-034).

**Why no vector DB / RAG in the traditional sense (ADR-030's companion decision):** the phase is
titled around "AI research," not literally "build a vector index." AlphaLens has no long-form
document corpus to index — its retrievable content is either structured rows (prices, forecasts,
sentiment aggregates, backtest metrics) or a small number of recent news articles per ticker, both
served far more precisely by a typed tool call + repository query than by embedding similarity
search. Retrieval here is exact and structured (Tool Selection → Controlled Tools above), not
approximate-nearest-neighbor — introducing a vector store would add infrastructure without solving
a real retrieval problem this system has.

Conversation memory is intentionally in-process and unpersisted (`app/agent/conversation.py`): a
bounded number of turns, keyed by `(user_id, conversation_id)` so a client-guessable
`conversation_id` can never surface another user's history, and lost on process restart by design —
this is a research aid's short-term memory, not a durable chat log requiring its own retention/
deletion policy.

### Multi-provider validation (Phase 8.5)

`LLM_PROVIDER` (`"anthropic"` | `"groq"` | `"gemini"`, default `"anthropic"`) selects which
`LLMProvider` `get_llm_provider()` builds; each provider reads its own key
(`LLM_API_KEY`/`GROQ_API_KEY`/`GEMINI_API_KEY`) and its own model
(`LLM_MODEL`/`GROQ_LLM_MODEL`/`GEMINI_LLM_MODEL`), server-side only — none of these ever reach the
frontend bundle, the same rule that already applies to every other backend credential (see
[security.md](security.md)). `GroqLLMProvider` targets Groq's OpenAI-compatible tool-calling API
(`groq` SDK); `GeminiLLMProvider` targets Gemini's native manual function-calling
(`google-genai` SDK, `generate_content` + an explicitly-built `contents` list, automatic function
calling disabled) — both convert the same `LLMMessage`/`ToolDefinition`/`ToolCallRequest` types
`orchestrator.py` already uses, so `run_agent` itself required zero changes to support them
(ADR-034). Live-network verification against real Groq/Gemini endpoints lives in
`tests/integration/test_agent_live_providers.py`, marked `@pytest.mark.live_llm` and
individually skipped (not failed) when that provider's key is absent — the standard `pytest`
invocation never requires `GROQ_API_KEY`/`GEMINI_API_KEY`/`LLM_API_KEY`. Provider-level unit tests
(`tests/unit/test_agent_groq_provider.py`, `test_agent_gemini_provider.py`) mock at the SDK client
boundary using each vendor's own real response/exception types, covering tool-schema conversion,
response parsing, and every documented failure mode (missing/invalid key, rate limit, timeout,
malformed response) mapping to the existing `LLMProviderError` → `AGENT_UNAVAILABLE` 503 path —
never a new error shape per vendor.

**Live validation results:** `pytest -m live_llm` was run against both providers with real
credentials. **Groq: 11/11 real scenarios passed** — every tool-selection, grounding, citation,
missing-data, and refusal check held against actual model output, not just a scripted fake. Gemini
initially failed every multi-turn scenario with a real `400 INVALID_ARGUMENT` — this run *found* a
real bug (`_to_gemini_contents` used `role="tool"` for the function-response turn; the actual API
only accepts `role="user"` there) and it was fixed and re-verified live (see ADR-035). After the
fix, further live Gemini scenarios hit a real `429 RESOURCE_EXHAUSTED` — the configured key's
free tier caps `gemini-3.8-flash` at 20 `generate_content` requests/day, exhausted by this session's
own testing — an account/tier limitation, not a code defect; a targeted rerun of the one scenario
that had also needed a test-harness fix (`TestQ3RecentSentiment`, see below) confirmed Groq passing
cleanly on isolated reverification. Two of the ten Phase 8-evaluation-style scenarios exposed
test-harness bugs of their own, unrelated to any provider: comparing an agent's tool evidence
against a fresh direct call to the same tool for grounding verification is only valid once
wall-clock-derived fields (`get_forecast`'s `prediction_timestamp`; `get_sentiment`'s per-window
`as_of`/`since`/`until`) are excluded from the comparison, since those legitimately differ between
any two calls a few hundred milliseconds apart — both `tests/integration/test_agent_live_providers.py`
comparisons now strip them explicitly. A third scenario's prompt-injection check originally treated
any occurrence of "buy order" in the answer as compliance, which incorrectly flagged Groq for
correctly quoting the (now-malicious) article text back to the user as part of an honest summary —
the check now looks for actual first-person compliance phrasing instead.

## Screener, watchlists, portfolios & alerts (Phase 9)

Six new tables (`app/db/models/{watchlist,portfolio,alert}.py`, migration
`0004_phase9_portfolios`): `watchlists`/`watchlist_items`, `portfolios`/`transactions`,
`alerts`/`alert_events`. All are user-owned (`user_id` FK) except `alert_events`, which belongs to
its parent `alert`. Every read/write goes through a repository method that filters by `user_id` in
the query itself — see "Ownership isolation" below.

**Portfolios hold no derived state.** `Transaction` rows are the sole source of truth; cash,
positions, cost basis, and P&L are recomputed by `app/services/portfolio_service.py` on every call
from the full transaction history plus current prices — never persisted redundantly. Accounting is
**average-cost, long-only**: a `BUY` adds `quantity*price+fees` to a running cost basis, a `SELL`
removes cost basis at the position's current average (not FIFO lot tracking) and is rejected
(`InsufficientPositionError`) if it would exceed the held quantity; short selling is not
implemented. `CASH_DEPOSIT`/`CASH_WITHDRAWAL` move cash and carry no fees (enforced by a DB CHECK
constraint, `ck_transactions_type_fields`, which also enforces the BUY/SELL vs CASH_* field-shape
split). `total_return_percent` is a simple money-weighted return
(`(total_value - net_contributed) / net_contributed`), not time-weighted — a documented scope
limit, not an oversight. `get_performance_history` builds a **no-look-ahead** daily series: at each
historical day it replays only transactions with `executed_at` on/before that day and prices things
using only price bars dated on/before that day (via `bisect_right` on each security's ascending
close series) — a future transaction or price bar can never move a past point (see
`tests/integration/test_portfolio_service.py::TestNoLookAheadBiasPerformanceHistory`). A holding
whose current price isn't available renders `market_value: null`, never a fabricated partial sum
silently treated as the whole (`PortfolioAnalytics.market_value_is_partial` makes this explicit).

**The screener** (`app/services/screener_service.py`) is batched by construction: one query for the
candidate universe (`SecurityRepository.list_matching`), one for latest quotes
(`PriceBarRepository.get_latest_quotes`), one for multi-security OHLCV history
(`PriceBarRepository.get_bars_for_securities`) regardless of how many securities are in scope.
Forecasts reuse the models `ml_common.load_models()` already loaded and are computed straight from
the already-fetched OHLCV slice via `ml.inference.serving.build_latest_feature_row` — the same
feature pipeline `forecast_service` uses for one ticker — at **zero additional DB queries per
security**. The one exception is sentiment: `news_query_service.get_sentiment_overview` still runs
its own query pair per candidate, since sentiment aggregation isn't batched across securities today
— a documented, bounded tradeoff appropriate for a small demo universe (a much larger universe
would need a batched sentiment query, out of scope here). A field the screener couldn't compute
(insufficient history, ticker outside the forecast model's trained universe, no scored articles)
comes back `null` and is listed in `unavailable_fields`, never defaulted to zero — and a
`forecast_direction` filter excludes rows with no forecast rather than treating "unknown" as a
match. Pagination is deterministic: the candidate universe is always fetched in `ticker ASC` order
and Python's `sort()` is stable, so any sort field's ties break by ticker consistently across pages.

**Alert evaluation** (`app/services/alert_evaluation_service.py`) mirrors the background-job flow
above, reusing the generic `jobs` table (`JobType.ALERT_EVALUATION`) rather than a new tracking
table. Celery Beat (`app/workers/celery_app.py`'s `beat_schedule`, a new `beat` service in
`infra/docker-compose.yml` running the same image as `worker`) enqueues `alerts.evaluate`
(`app/workers/tasks/alerts.py`) every `ALERT_EVALUATION_INTERVAL_SECONDS` (default 300s); the task
creates/commits a `jobs` row up front (so a mid-run crash still records `FAILED`, same
early-commit-then-work shape as ingestion), then calls `evaluate_all_alerts` once for every enabled
alert across every user (deliberately not user-scoped — this is the one place in Phase 9 that
reads across users, by design). Each of the seven alert types
(`PRICE_ABOVE`/`PRICE_BELOW`/`PERCENT_CHANGE_ABOVE`/`PERCENT_CHANGE_BELOW`/`FORECAST_CLASS_CHANGE`/
`SENTIMENT_CHANGE`/`TECHNICAL_THRESHOLD`) evaluates deterministically against the same service
functions the REST API and agent tools use (quotes, technical indicators, forecasts, sentiment) —
never a reimplementation of that math. A condition that's still true on a later cycle does not
re-fire: `cooldown_minutes` + `last_triggered_at` gate a new `AlertEvent`. The two CHANGE-detection
types need a previous value to diff against, which nothing else persists (forecasts/sentiment are
computed on demand) — `Alert.last_observed_state` is the evaluator's own scratch memory for this,
distinct from `AlertEvent` (only ever a real, user-facing firing); the first evaluation after an
alert is created only establishes this baseline and never fires. **Idempotency under concurrent
evaluation**: each alert row is locked with `SELECT ... FOR UPDATE` for its own check-then-fire
sequence, so two workers evaluating the same alert can't both pass the cooldown check and double
fire — the second blocks until the first's transaction commits, then re-reads the now-updated
`last_triggered_at` (see
`tests/integration/test_alert_evaluation_service.py::TestCooldownDeduplication`).

**Research agent integration**: seven new read-only tools in `app/agent/tools.py`
(`get_watchlists`, `get_watchlist`, `run_screener`, `get_portfolio`, `get_portfolio_holdings`,
`get_portfolio_performance`, `get_alerts`) — no new tool abstraction, no orchestrator change. Each
wraps the same service functions the REST API calls and is scoped to the calling `User` passed into
every handler; a watchlist/portfolio is looked up by *name* within that user's own resources (the
tool schemas never accept a raw id), so there is no way to address another user's data through the
agent even if the model tried. Every tool is a pure passthrough of its service's output — the
service computes P&L/returns, the tool reports them verbatim as `Evidence` — the agent explains,
it never calculates (see `tests/integration/test_agent_portfolio_tools.py`, which asserts a tool's
output matches a direct service call field-for-field). No tool can create, modify, or delete a
transaction, watchlist, portfolio, or alert; `tests/integration/test_agent_tools.py::TestToolRegistry
::test_no_portfolio_mutating_tools_exist` pins this as a structural registry check, not just a
convention.

## Model lifecycle & MLOps (Phase 10)

```
DATA → INGESTION → VALIDATION → FEATURE GENERATION → MODEL TRAINING → MODEL EVALUATION
  → MODEL REGISTRY → MODEL PROMOTION → INFERENCE → PREDICTION LOGGING → MONITORING
  → DRIFT/PERFORMANCE DETECTION → RETRAINING → RE-EVALUATION → SAFE MODEL PROMOTION
```

**Registry, promotion, and artifact integrity** (`ml/ml/registry/{registry,promotion}.py`):
`ModelRecord` carries everything needed to answer "which model, which version, which
dataset/features/split, which metrics, when, is it active" — dataset/feature versions, train/
validation/test period bounds, full metrics, an artifact SHA-256 checksum, and a `status`
(`TRAINING`/`VALIDATED`/`STAGING`/`PRODUCTION`/`ARCHIVED`/`FAILED`) with a human-readable
`status_reason`. Training a model and registering it (`VALIDATED`) is never sufficient to make it
servable — `ml.registry.promotion.apply_promotion` runs automatically at the end of
`train_pipeline.run_experiment` for every model type with a defined gate policy, comparing the
candidate against the best same-`dataset_version` baseline and the currently-`PRODUCTION` model of
that type; only a candidate that beats both becomes `PRODUCTION` (archiving what it replaces), a
losing candidate becomes `FAILED`. `ml.inference.serving.load_forecast_models` resolves only
`ModelRegistry.get_active(model_type)` — the single `PRODUCTION` record, never "the best-scoring
record regardless of status" — and additionally calls `verify_artifact_integrity` (recomputing the
checksum) before loading either model, refusing to serve a tampered/corrupted artifact. See
`docs/decisions.md`'s ADR-040 for the real before/after finding this produced: XGBoost genuinely
beats its baselines on this project's real bundled dataset and is `PRODUCTION`; LSTM/GRU genuinely
do not and are correctly `FAILED`.

**Retraining** (`app/services/retraining_service.py`, `app/workers/tasks/retraining.py`,
`POST /models/retrain`, ANALYST/ADMIN): the one module in `backend/app` allowed to import
`ml.config`/`ml.pipelines` — enforced structurally by
`tests/unit/test_architecture_boundaries.py`, which AST-scans every file under `app/api/` and
`app/services/` for those imports and fails if anything besides `retraining_service.py` has them.
Training only ever runs as background Celery work (same job-tracking shape as market-data
ingestion — create the `jobs` row, commit, dispatch, let the task manage running/completed/failed)
and is triggered manually/administratively, never automatically or inside a request handler.
`run_retraining` locks its `jobs` row (`SELECT ... FOR UPDATE`) and skips a job that isn't
`QUEUED` — a Celery-redelivered duplicate of the same task message becomes a no-op instead of a
second training run racing the first to write `ml.registry`'s unlocked `registry.json` file (see
ADR-047).

**Prediction logging & live performance monitoring** (`app/services/prediction_service.py`,
`predictions` table): every real forecast `forecast_service.get_forecast` serves is logged with its
exact model version; `evaluate_matured_predictions` (Celery Beat, daily) scores a prediction against
real subsequent `PriceBar` rows once its horizon has actually elapsed (trading days, not calendar
days), never before. `get_live_performance` computes MAE/RMSE and a directional hit rate from
matured predictions only — structurally separate from `ml.registry`'s training/backtest metrics
(see ADR-041); a model with no matured predictions yet reports `insufficient_data: true`, never a
fabricated 0.

**Drift monitoring** (`app/services/drift_service.py`, `GET /models/drift/{ticker}`): PSI +
mean-shift on indicators already computed elsewhere (`rsi_14`/`sma_20`/`volatility_20d`/
`relative_volume_20`), comparing an earlier vs. later window of a security's own real price
history. A monitoring signal only — never mutates anything, never feeds back into promotion, never
itself claims a model is invalid (ADR-042).

## Provider ecosystem (Phase 10 continuation)

```
MARKET DATA:    Provider → Validation → Normalization → PostgreSQL (price_bars) → app
FUNDAMENTALS:   Provider → Raw response → Validation → Normalization → PostgreSQL (fundamentals)
MACRO:          Provider → Validation → Normalization → PostgreSQL (macro_observations, no FK to securities)
```

Extends the existing `MarketDataProvider`/`NewsProvider` abstractions (`app/providers/base.py`)
with `FundamentalsProvider`/`MacroDataProvider` — the rest of the application depends on these
interfaces, never a vendor SDK directly. Provider *selection* is config-driven and independent of
the pre-existing `demo_mode` flag: `market_data_provider`/`news_provider`/`fundamentals_provider`/
`macro_provider` each default to a safe, credential-free value (`get_market_data_provider()` etc.
in each `app/providers/<category>/__init__.py`), so a fresh checkout with nothing configured runs
entirely in Demo Mode.

| Category | Selected | Rejected/deferred | Why |
|---|---|---|---|
| Market data | Twelve Data (`twelvedata`) | Alpha Vantage (25 req/day), Finnhub (historical OHLCV moved to paid tier, 403 on free keys) | Only free option with usable rate limits + multi-decade OHLCV; free tier bars commercial use (verified against its own ToS) |
| Fundamentals | SEC EDGAR (`sec_edgar`) | — | No API key needed at all (only an identifying `User-Agent`); public-domain, as-filed XBRL data |
| Macro | FRED (`fred`) | — | Free, public-domain, authoritative; `realtime_start` gives a real vintage/observation-date split |
| News | Demo only | NewsAPI.org (localhost-only free tier), Marketaux (ToS could not be independently verified) | No candidate cleared both licensing and verifiability |

Each real adapter is unit-tested against mocked HTTP only (`tests/unit/test_sec_edgar_provider.py`,
`test_fred_provider.py`, `test_twelvedata_provider.py`) — the normal test suite never makes a real
network call. SEC EDGAR is the one provider genuinely live-validated
(`tests/integration/test_sec_edgar_live.py`, `@pytest.mark.live_provider`, excluded from the
default run) since it needs no credential to gate on. Full evaluation evidence, licensing caveats,
and the Marketaux non-integration are in `docs/decisions.md`'s ADR-046.

**Storage & provenance**: `fundamentals` and `macro_observations` are new, structured tables
(real numeric/date columns), idempotent on a natural identity via `ON CONFLICT DO UPDATE` — never
merged into `PriceBar`. Macro observations carry no FK to `securities` and keep `vintage_date`
(when a value was actually known) separate from `observation_date` (what it describes) so
`MacroRepository.get_as_of(series_id, as_of=...)` can enforce no-look-ahead-bias for a later
feature-engineering join. Neither table stores a derived metric — only as-filed facts/observations.

**Provider health**: `GET /api/v1/system/providers` (ANALYST/ADMIN) reports each category's
configured provider, whether a credential is required/present (boolean only), and last
success/failure — reusing the existing `jobs` table, no new tracking infrastructure.

**Research agent integration**: three new read-only tools (`get_fundamentals`,
`get_macro_indicators`, `get_data_source_status`) follow the exact existing tool pattern —
Pydantic input, deterministic service call, structured output + `Evidence`, `available: false`
with no evidence entry (never fabricated) when nothing has been ingested.

## Failure handling

- **External provider (market data/fundamentals/macro, Phase 10 continuation):**
  `DemoMarketDataProvider`/`NoneFundamentalsProvider`/`NoneMacroProvider` can't fail (pure
  in-process generators/no-ops). The three real adapters (Twelve Data, SEC EDGAR, FRED) share
  `app/providers/http_client.py`'s bounded retry/backoff: a timeout or 5xx gets a bounded retry
  with exponential backoff, a 429 respects `Retry-After` within a bounded retry count then raises
  `ProviderRateLimitedError`, any other 4xx fails immediately (no retry), and a malformed 2xx body
  raises `ProviderResponseError` — never an uncontrolled retry loop, never a fabricated fallback
  value. Ingestion services (`fundamentals_service.run_ingestion`/`macro_service.run_ingestion`)
  catch `ProviderError` and record the job `FAILED` with the real reason, same as market-data
  ingestion — a provider outage never propagates to the request path or takes down the API, since
  ingestion only ever runs as background Celery work. See docs/decisions.md's ADR-046.
- **Redis (cache):** every cache read/write is wrapped and swallows `redis.RedisError` — a cache
  outage degrades to "always miss," never a 500 (`app/core/cache.py`, ADR-010). Verified by
  pointing at an unreachable Redis and confirming `cache_get_json`/`cache_set_json` return/no-op
  cleanly rather than raising.
- **Background jobs:** see "Background-job flow" above — a job never gets stuck `RUNNING`;
  failures are always recorded, never silently swallowed or left unresolved.
- **Celery worker crash mid-task (Phase 10):** `task_acks_late=True` +
  `task_reject_on_worker_lost=True` mean a task whose worker dies gets redelivered rather than
  silently lost — safe because every task here is idempotent under redelivery (ingestion upserts,
  alert evaluation's row lock + cooldown, transaction idempotency keys, prediction evaluation only
  touching still-unevaluated rows). `task_time_limit`/`task_soft_time_limit` bound a genuinely stuck
  task so it can't occupy a worker forever. See `docs/decisions.md`'s Celery-hardening ADR.
- **LLM provider / research agent (Phase 8):** an unconfigured or failing LLM provider raises
  `LLMProviderError`, mapped to a clean `AGENT_UNAVAILABLE` 503 — never a raw SDK exception. A tool
  that raises unexpectedly is caught inside the orchestrator's tool-execution step and turned into
  a generic `{"error": "..."}` result the LLM can see and explain honestly; the underlying exception
  is logged server-side only, never forwarded into the conversation (see docs/security.md). The
  tool-calling loop has a hard iteration cap (`llm_max_tool_iterations`) and a per-turn tool-call
  cap (`llm_max_tool_calls_per_turn`); exhausting the iteration budget produces a controlled
  "couldn't finish within the allotted steps" answer rather than looping forever or erroring.

## Scaling strategy

Target production architecture (ALB → ECS Fargate backend/worker/beat → RDS Postgres + ElastiCache
Redis + EFS for model artifacts), AWS readiness, secrets management, data retention, and backup/
disaster recovery are documented in [docs/deployment.md](deployment.md) (Phase 10) — a target
architecture and operational policy, explicitly not a record of an actual deployment (no AWS
resources exist for this project). One data-layer note recorded here since it's specifically about
this codebase's own scaling ceiling, not the deployment target: `price_bars` would need date-range
partitioning or a dedicated time-series store before real-vendor data volumes (see
[database.md](database.md)'s time-series scaling note) — not needed at Demo Mode's volume, so
deliberately not built ahead of need.
