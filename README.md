# AlphaLens

**AI-powered market intelligence, forecasting, research, and portfolio analytics.**

AlphaLens is a full-stack platform for market research, quantitative analysis, and forecasting
experimentation: historical price/technical charting, an ML forecasting engine (direction +
expected-return range, not exact-price prediction), financial-news sentiment, an explainable
stock screener/ranking system, portfolio and watchlist tracking, alerts, a backtesting engine, a
model-comparison lab, and research-report generation.

> **Not financial advice.** AlphaLens provides analytical and educational information only.
> Predictions are probabilistic and may be wrong. Historical backtests do not guarantee future
> performance. See [docs/security.md](docs/security.md) and the in-app disclosures.

## Project status

This repository is being built in phases (see [Roadmap](#roadmap) below). Each phase is fully
functional and tested before the next begins — there are no placeholder "coming soon" features
for anything marked complete below.

- [x] **Phase 1 — Repo & infra foundation.** Docker Compose stack (Postgres, Redis, FastAPI
      backend, Vite/React frontend), health/readiness endpoints, lint/format/type-check tooling,
      CI skeleton.
- [x] **Phase 2 — Auth & core domain.** Register/login/logout, JWT access + rotated refresh-token
      cookie, forgot/reset password (Demo Mode email via `ConsoleEmailProvider`), change password,
      account deletion, role-based authorization (`USER`/`ANALYST`/`ADMIN`), rate limiting, audit
      log. `users`/`sessions`/`password_reset_tokens`/`audit_logs` tables + migration. Frontend
      login/register/forgot-password/reset-password pages, a protected route, and silent session
      restore on load. 28 backend tests (unit + API, real Postgres) and 16 frontend tests.
- [x] **Phase 3 — Market data platform.** `MarketDataProvider` abstraction + `DemoMarketDataProvider`
      (synthetic, seeded, deterministic prices for ~10 real tickers — clearly labeled
      `data_source: "demo"` everywhere, never presented as real). Idempotent OHLCV ingestion
      (upsert on `(security_id, ts)`) with data-quality validation, running in a real Celery
      worker against a real Redis broker (both previously declared-but-unwired — fixed as part of
      this phase). Generic `jobs` table/endpoint. `GET /stocks`, `/stocks/{ticker}`,
      `/stocks/{ticker}/prices`, `POST /market-data/ingest` (first RBAC-gated endpoint, proven live),
      `GET /jobs/{id}` — all Redis-cached with graceful degradation if Redis is down. Frontend Stock
      Explorer (search/filter/paginate) and Stock Detail (quote, 52-week range, candlestick chart
      via lightweight-charts, range selector) with real loading/empty/error states and a persistent
      demo-data banner; a real app shell/nav layout. 71 backend tests (96% coverage, real
      Postgres+Redis) and 27 frontend tests. Verified against real running processes end to end,
      not just automated tests — see [docs/testing.md](docs/testing.md).
- [x] **Phase 4 — Dashboard & market overview.** `GET /dashboard/overview`: market summary
      (tracked/with-data counts, data freshness), market movers (top gainers/losers/most-active —
      real daily returns via one window-function query across every security, not N+1), sector
      performance (equal-weighted average return per sector actually present in the data), market
      breadth (advancing/declining/unchanged, computed against one shared reference date so it's a
      real breadth measure, not securities compared across different days), and recently-updated
      securities. Every section has an honest "not enough data yet" shape before any ingestion —
      no fabricated zeros. Frontend dashboard at `/app` replaces the Phase 2 placeholder: summary
      cards, movers panels, a sector bar visualization, a breadth bar, and a recent-activity table,
      all built from the existing design system (no new UI library). 99 backend tests (97%
      coverage) and 31 frontend tests. Two real bugs found via a manual cross-endpoint E2E check
      (not by inspection) and fixed: a model/migration timezone mismatch affecting every
      `datetime` column project-wide, and two endpoints computing "the same" percent return via
      different formulas that disagreed in Decimal's last few digits — see ADR-013/ADR-014 in
      [docs/decisions.md](docs/decisions.md). Portfolio summary and watchlist widgets (part of the
      original spec's "full Dashboard module") are deferred until Phase 9 builds the underlying
      portfolio/watchlist tables — a dashboard card with no real position data behind it would be
      exactly the fabricated-metric anti-pattern this phase was built to avoid. The marketing
      landing page is deferred to whenever the pre-login experience is prioritized.
- [x] Phase 5 — ML foundation: research-data provider, validation, 27-feature engineering,
      return/direction targets, chronological datasets, naive baselines, XGBoost, LSTM, GRU,
      classification/regression/financial evaluation, JSON model registry, inference interface.
      Standalone (`ml/` imports nothing from `backend/`, no FastAPI dependency — ADR-001), not yet
      wired into the API. Real results (11 tickers, 2013–2018, real MIT-licensed historical OHLCV
      — never the synthetic demo-mode data) are reported honestly as pipeline validation, not as
      investment-grade performance — see [docs/ml-pipeline.md](docs/ml-pipeline.md).
- [x] Phase 6 — ML serving, explainability & portfolio backtest foundation: `ml.inference` wired
      into the backend (`GET /stocks/{ticker}/forecast`, real XGBoost inference, never trains
      inside a request — ADR-001), SHAP explainability (`GET /forecast/explanation`), a portfolio
      backtest engine (`ml.backtest`, `POST /research/backtest`) fixing Phase 5's per-ticker-only
      evaluation gap (ADR-018/024), one real walk-forward example. Every forecast/backtest response
      discloses `data_source` — this deployment's Demo Mode data by default, honestly labeled as
      carrying no real predictive meaning (ADR-023). Frontend: an AI Forecast card + "why this
      prediction" on Stock Detail, a `/research/backtest` research page. See
      [docs/ml-pipeline.md](docs/ml-pipeline.md) for full methodology and results.
- [x] Phase 7 — Financial NLP & news intelligence: a `NewsProvider` abstraction (`DemoNewsProvider`
      today — clearly-labeled synthetic headlines, never presented as real news), real FinBERT
      sentiment (`ml.nlp.sentiment`, pinned model revision, never hardcoded), entity/ticker mapping
      against the `securities` table (ticker-symbol + case-sensitive company-name matching — no
      invented tickers, ADR-026), leakage-free temporal sentiment aggregation (`GET
      /stocks/{ticker}/news`, `/sentiment`, `/sentiment/history`), async ingestion via the existing
      Celery worker (`POST /news/ingest`). Idempotent end to end (articles, entity matches, and
      sentiment each dedupe on their own unique constraint). Sentiment is documented throughout as
      an informational signal, not a demonstrated trading signal — no experiment in this phase
      claims otherwise. See [docs/ml-pipeline.md](docs/ml-pipeline.md) "News & sentiment pipeline."
- [x] Phase 8 — AlphaLens AI Research Agent: a grounded LLM research assistant
      (`app/agent/`) that reasons over AlphaLens's existing structured data through 9 controlled,
      typed tools (quote, price history, technical indicators, forecast, SHAP explanation, news,
      sentiment, sentiment history, backtest) — never a general-purpose chatbot, never a source of
      data or calculation itself (the LLM selects tools and synthesizes an answer; every fact traces
      back to a tool's structured `Evidence`). A vendor-agnostic `LLMProvider` abstraction
      (`AnthropicLLMProvider` in production, a deterministic `FakeLLMProvider` for the entire test
      suite — no external API key required to run it), a bounded tool-calling loop (hard iteration
      and per-turn tool-call caps), a versioned static system prompt, two-layer prompt-injection
      defense (system prompt + per-tool-result wrapping), inline evidence citations
      (`[Forecast]`/`[SHAP]`/`[News]`/...), bounded per-`(user, conversation)` in-memory
      conversation history (never persisted, never cross-user), and structured retrieval instead of
      a vector DB (no long-form corpus exists to index — ADR-030). No trading, portfolio mutation,
      retraining, or arbitrary code execution capability exists or is reachable. `POST
      /research/chat`, rate-limited (20/hour); a `/app/research/chat` frontend page. 89 new backend
      tests (agent unit/integration/security/evaluation/API, 276 backend tests total) and 8 new
      frontend tests (57 total) — see [docs/architecture.md](docs/architecture.md) "Research agent
      flow", [docs/security.md](docs/security.md) "Research agent (Phase 8)", and
      [docs/decisions.md](docs/decisions.md) ADR-029–033.
- [x] Phase 8.5 — Multi-provider live LLM validation: two more real `LLMProvider`
      implementations, `GroqLLMProvider` (Groq's OpenAI-compatible tool-calling API) and
      `GeminiLLMProvider` (Gemini's native manual function-calling, automatic function calling
      disabled so the orchestrator always owns the loop) — added with **zero changes** to
      `app/agent/orchestrator.py`, proving the Phase 8 `LLMProvider` abstraction is real, not just
      aspirational. Provider selection via `LLM_PROVIDER` (`anthropic`/`groq`/`gemini`, default
      `anthropic`); each provider's key/model is its own env var, server-side only, never sent to
      the frontend. Neither provider ever enables its vendor's own built-in server-side tools
      (Groq web search/code execution; Gemini `google_search`/`code_execution`/`computer_use`) —
      only AlphaLens's existing 9 function tools are ever declared, verified structurally by test.
      37 new backend tests (11 Groq + 16 Gemini provider-level, mocked at the SDK boundary with
      each vendor's own real response/exception types; 10 provider-registry tests) plus 22
      live-network tests (`tests/integration/test_agent_live_providers.py`, marked
      `@pytest.mark.live_llm`, individually skipped when a key is absent — the standard `pytest`
      invocation still needs no LLM credentials at all). 335 backend tests total (313 passed + 22
      correctly-skipped live tests without credentials), 0 regressions.
      **Live-validated with real credentials:** Groq passed **11/11** real scenarios; live testing
      against Gemini found and fixed a real bug (`_to_gemini_contents` sent `role="tool"` for a
      tool-result turn — the actual API rejects that with `400 INVALID_ARGUMENT` and only accepts
      `role="user"` there, per ADR-035), after which further live Gemini scenarios were blocked by
      a real `429` free-tier quota limit (20 requests/day), not a code issue. See
      [docs/architecture.md](docs/architecture.md) "Multi-provider validation (Phase 8.5)",
      [docs/security.md](docs/security.md), and [docs/decisions.md](docs/decisions.md)
      ADR-034/035.
- [x] Phase 9 — Screener, Watchlists, Portfolios & Alerts: a real market-intelligence workflow
      on top of the existing ML/data layers — no fabricated numbers anywhere. **Watchlists**
      (`watchlists`/`watchlist_items`) with idempotent add/remove and batched-quote enrichment.
      **Screener** (`app/services/screener_service.py`) filtering/sorting/paginating the tracked
      universe by price, day change, 20-day return, RSI, forecast direction, and sentiment —
      batched to a fixed 3 queries regardless of universe size, forecasts computed by reusing the
      loaded models against already-fetched OHLCV (zero extra DB queries per security), and any
      field it can't compute (insufficient history, untrained ticker) comes back `null` in
      `unavailable_fields`, never a fabricated zero. **Portfolios** (`portfolios`/`transactions`,
      `BUY`/`SELL`/`CASH_DEPOSIT`/`CASH_WITHDRAWAL`) where transactions are the sole source of
      truth — average-cost basis, long-only, fee-aware, idempotency-key deduplication — and a
      no-look-ahead-bias performance history built from real transaction/price replay per day
      (dedicated adversarial tests prove a future transaction/price can never move a past point).
      **Alerts** (7 deterministic types: price/percent-change thresholds, forecast-class change,
      sentiment shift, technical-indicator threshold) evaluated on a Celery Beat schedule
      (`app/workers/tasks/alerts.py`, reusing the generic `jobs` table's `JobType.ALERT_EVALUATION`
      — ADR-039) with cooldown/deduplication and `SELECT ... FOR UPDATE` row-locking making
      evaluation idempotent under concurrent workers. **Research agent**: 7 new read-only tools
      (`get_watchlists`/`get_watchlist`/`run_screener`/`get_portfolio`/`get_portfolio_holdings`/
      `get_portfolio_performance`/`get_alerts`) — no `execute_trade`/mutation tool exists or is
      planned; the application computes every number, the agent only explains it. Ownership
      isolation (watchlist/portfolio/alert/transaction access always 404s, never 403s, for a
      non-owner — extending the Phase 1 account-enumeration-resistance philosophy) is covered by
      dedicated cross-user tests for all three resource families. `/app/screener`,
      `/app/watchlists(/:id)`, `/app/portfolio(/:id)`, `/app/alerts` frontend pages. 71 new backend
      tests (406 backend tests total: 384 passed + 22 correctly-skipped live LLM tests, 0
      regressions) and 13 new frontend tests (70 total) — see
      [docs/architecture.md](docs/architecture.md) "Screener, watchlists, portfolios & alerts
      (Phase 9)", [docs/security.md](docs/security.md) "Ownership isolation (Phase 9)", and
      [docs/decisions.md](docs/decisions.md) ADR-036–039.
- [x] Phase 10 — MLOps, Productionization & Deployment: a real production lifecycle on top of
      Phases 5-9's ML/data layers, not new buzzword infrastructure. **Model promotion gate**
      (`ml.registry.promotion`, ADR-040) — fixed a real pre-existing gap where `status` was
      decorative (`load_forecast_models` picked the best-scoring record regardless of status); a
      candidate now becomes `PRODUCTION` only if it beats its baseline AND doesn't regress vs. the
      current `PRODUCTION` model, with a SHA-256 artifact-checksum integrity check before loading.
      Real, honest result on this project's own dataset: XGBoost return/direction models
      genuinely beat their baselines and are `PRODUCTION`; LSTM/GRU genuinely do NOT and are
      correctly `FAILED` — not forced to pass. **Retraining** via a Celery task
      (`POST /models/retrain`, ANALYST/ADMIN) — the only backend module allowed to import
      training code, enforced by an AST-scanning structural test. **Prediction logging & live
      performance monitoring** (`predictions` table, daily Celery Beat evaluation against real
      subsequent price bars) — kept structurally separate from training/backtest metrics.
      **Drift monitoring** (PSI + mean-shift on existing indicators) — a monitoring signal, never
      an automatic verdict. **Production config safety** — refuses to start with
      `ENVIRONMENT=production` and an insecure JWT secret/cookie/CORS origin (ADR-045).
      **Health/readiness split** — `/ready` now returns a real 503 (not just a 200 with a string)
      and checks Redis non-fatally. **Celery hardening** — `acks_late`/reject-on-worker-lost/
      single-prefetch/time limits, safe because every task here is idempotent under redelivery.
      **Docker productionization** — multi-stage, non-root backend image; a missing
      `.dockerignore` was found and fixed (a multi-GB local `.venv` was being sent as build
      context). **CI** — fixed a real pre-existing gap where `backend-ci.yml` never installed the
      `ml` package (nearly the entire suite would `ModuleNotFoundError` in real CI) and where
      `ml-ci.yml` never ran the 205 real tests that already existed; added `pip-audit`/gitleaks/
      Trivy scanning and a migration downgrade check. **Deployment architecture** documented
      (ALB → ECS Fargate → RDS/ElastiCache/EFS — see [docs/deployment.md](docs/deployment.md)) —
      a target architecture, explicitly not a claim of an actual AWS deployment. **Frontend**:
      route-level code-splitting cut the main JS bundle from 616 KB to 282 KB (measured), with
      Vite's "chunk larger than 500 KB" warning gone. **Data-quality hardening**: added
      future-timestamp rejection and abnormal-price-move (WARNING-tier) detection to the
      existing ingestion validator. 47 new backend tests (453 backend tests total: 431 passed +
      22 correctly-skipped live LLM tests) plus 232 ml/ package tests (up from 205 — new
      registry/promotion/pipeline-integration tests), 0 regressions — see
      [docs/architecture.md](docs/architecture.md) "Model lifecycle & MLOps (Phase 10)",
      [docs/security.md](docs/security.md) "Production hardening (Phase 10)",
      [docs/deployment.md](docs/deployment.md), and [docs/decisions.md](docs/decisions.md)
      ADR-040–045.
- [x] Phase 10 continuation — Real Data Provider Ecosystem: extended `MarketDataProvider`/
      `NewsProvider` with `FundamentalsProvider`/`MacroDataProvider` (ADR-046), each candidate
      genuinely evaluated (not assumed) against its own official docs/terms. **Selected**: Twelve
      Data (market data — free tier bars commercial use, verified against its own ToS, not a
      third-party summary that claimed otherwise), SEC EDGAR (fundamentals — needs no API key,
      live-validated in this session), FRED (macro — public-domain, real vintage/observation-date
      split). **Rejected/deferred with reasons documented**: Alpha Vantage, Finnhub, NewsAPI.org,
      Marketaux (ToS page could not be independently verified — left unimplemented rather than
      integrated on trust). Provider selection is now config-driven
      (`MARKET_DATA_PROVIDER`/`NEWS_PROVIDER`/`FUNDAMENTALS_PROVIDER`/`MACRO_PROVIDER`),
      independent of the pre-existing `demo_mode` flag, defaulting to credential-free Demo Mode.
      New `fundamentals`/`macro_observations` tables (structured, provenance-carrying, idempotent
      upserts) — never merged into `PriceBar`; macro observations keep no FK to securities and
      preserve a `vintage_date` separate from `observation_date` for no-look-ahead-bias feature
      joins. `GET /api/v1/system/providers` reports provider health via the existing `jobs` table
      (no new infrastructure), never exposing a credential value. Three new read-only agent tools
      (`get_fundamentals`, `get_macro_indicators`, `get_data_source_status`). Every real adapter is
      unit-tested against mocked HTTP only; the one live test (`@pytest.mark.live_provider`, SEC
      EDGAR, excluded from the default run) was actually run against the real API in this session
      and passed. 65 new backend tests (529 backend tests total: 505 passed + 22 correctly-skipped
      live-LLM + 2 explicitly-gated live-provider), 0 regressions — see
      [docs/architecture.md](docs/architecture.md) "Provider ecosystem (Phase 10 continuation)",
      [docs/security.md](docs/security.md) "Provider ecosystem credentials (Phase 10
      continuation)", and [docs/decisions.md](docs/decisions.md) ADR-046.
- [x] Phase 10 finalization — MLOps + Productionization audit (ADR-047): audited the full
      lifecycle (registry → promotion → retraining → prediction logging → monitoring → drift) plus
      health/readiness, Celery/Redis, CI/CD, security, and frontend — found intact, nothing
      rebuilt. Two genuine gaps fixed: a **retraining duplicate-delivery guard**
      (`JobRepository.get_by_id_locked` + a `QUEUED`-only check, mirroring alert evaluation's
      existing row-lock pattern) protecting `ml.registry`'s unlocked `registry.json` from a
      Celery-redelivered duplicate training run; and **skipped-record visibility** for SEC
      EDGAR/FRED parsing (structured warning logs with seen/parsed/skipped counts — no malformed
      record is ever silently dropped without a trace). Full regression: 517 backend tests (511
      passed + 22 correctly-skipped live-LLM + 2 explicitly-gated live-provider), 232 ml tests, 70
      frontend tests, frontend lint/typecheck/build all clean, `docker compose config` valid — 0
      regressions. **Docker production image build was attempted but did not complete**: it ran
      into severe I/O contention from the host disk's pre-existing, unrelated near-full condition
      (Docker Desktop's 90+GB WSL VHDX — not caused by this project's code) and was cancelled per
      explicit instruction not to retry into disk exhaustion; see ADR-047 for the full incident and
      recovery. See [docs/decisions.md](docs/decisions.md) ADR-047.
- [x] Phase 10.5 — Product UI & Intelligence Experience (ADR-048): rebuilt the frontend as a
      dense analytical interface over the existing backend/ML system — no new backend
      capability, no new infrastructure. Shell (real global search, real alerts indicator),
      a shared design system (`DataTable`, `MetricCard`, `StatusBadge`, `SignalBadge`,
      `EvidenceCard`, `ChartContainer`, centralized `lib/format.ts`), and every page redesigned:
      Dashboard (real "AI Signals" panel), Stock Detail (tabbed, interactive real SHAP
      contribution bars, a Technicals tab from the full 27-feature explanation), Screener
      (wired two filter params the backend already supported but the frontend never forwarded,
      backend-driven sort), Watchlists (bounded real per-ticker AI signal column), Portfolio
      (a real value-over-time chart and allocation breakdown), Alerts (real per-alert trigger
      history via a previously-unused endpoint), Backtest (a real drawdown chart, execution
      assumptions), and a Research Assistant redesign with honest, differentiated error states.
      **Root-caused** the Assistant's permanent unavailability to a real missing-credential
      environment condition — deliberately did not wire the test-only `FakeLLMProvider` into the
      live chat path, since its finite scripted-response design would produce answers unrelated
      to a real user's question once exhausted. **Found and fixed a real backend bug**: slowapi's
      rate-limit handler was registered ahead of the app's own generic HTTP-exception handler,
      breaking the standard `{"error": {"code","message"}}` envelope on every 429 in the app, not
      just chat (`app/main.py`). 99 frontend tests (up from 74) across 20 files (up from 17),
      lint/typecheck/build clean, full 511-test backend suite re-passes with the fix. Real E2E
      validated at the HTTP level (registration, ingestion, dashboard, forecast at both default
      and full feature count, screener, watchlist, portfolio cash/buy/analytics/performance,
      alerts, backtest, provider status, and the honest chat-unavailable path) — no
      screenshot/browser tooling was available in this environment, so pixel-level visual QA was
      not performed; component tests and live API-contract checks stand in for it. See
      [docs/decisions.md](docs/decisions.md) ADR-048.
- [ ] Phase 11 — Jobs UX, WebSockets
- [ ] Phase 12 — Reports & PDF generation
- [ ] Phase 13 — Admin dashboard & observability UI
- [ ] Phase 14 — Testing hardening
- [ ] Phase 15 — Further CI/CD, security pass, docs

## Architecture

```
Frontend (React/TS)  →  Backend API (FastAPI)  →  PostgreSQL
                              │                     Redis (cache DB0 + Celery broker DB1/backend DB2)
                              ├── ml/ (standalone package, installed into the backend's venv as an
                              │   editable local package — ADR-021): data (validation, Research-
                              │   DataProvider) → features (fs_v1, 27 trailing-only) → targets
                              │   (return/direction) → datasets (chronological split, tabular +
                              │   sequence) → models (naive, XGBoost, LSTM, GRU) → evaluation
                              │   (classification/regression/financial) → registry (JSON) →
                              │   inference (serving.py: raw history → live forecast) →
                              │   explainability (SHAP, XGBoost) → backtest (portfolio engine) →
                              │   nlp (FinBERT sentiment, ml.nlp.sentiment). Training via
                              │   ml/scripts/run_real_experiment.py, never inside an HTTP request;
                              │   backend imports inference/explainability/backtest/nlp only, never
                              │   training (ADR-001) — GET /stocks/{ticker}/forecast(/explanation),
                              │   POST /research/backtest, GET /stocks/{ticker}/news(/sentiment).
                              ├── Celery worker (market_data.ingest, news.ingest,
                              │   alerts.evaluate on a Beat schedule — Phase 9, ADR-039;
                              │   training/reports add tasks here later, not new infra)
                              ├── providers/ (one ABC per phase that needs it — ADR-002):
                              │   EmailProvider (Phase 2), MarketDataProvider (Phase 3,
                              │   DemoMarketDataProvider today), NewsProvider (Phase 7,
                              │   DemoNewsProvider today), Fundamentals later
                              ├── Phase 9 — screener/watchlists/portfolios/alerts: watchlists +
                              │   screener_service (batched filters over quotes/returns/
                              │   forecast/sentiment, ADR-038) → GET /screener,
                              │   /watchlists(/:id); portfolio_service (transactions are the sole
                              │   source of truth, average-cost/long-only, no-look-ahead
                              │   performance history — ADR-036/037) → /portfolios(/:id)
                              │   (holdings/analytics/performance/transactions);
                              │   alert_evaluation_service (7 deterministic alert types, cooldown
                              │   + row-locked idempotency — ADR-039) → /alerts(/:id/events).
                              └── agent/ (Phase 8 — grounded LLM research agent): LLMProvider
                                  (Anthropic/Groq/Gemini in prod — LLM_PROVIDER selects which,
                                  Phase 8.5 — plus a deterministic fake for the whole test suite)
                                  → bounded tool-calling loop → 16 controlled tools (9 from
                                  Phases 5-8 + 7 read-only Phase 9 tools), each wrapping an
                                  existing service above (no new data/calc path) → structured
                                  Evidence + inline citations → grounded answer.
                                  POST /research/chat. No trading/writes/retraining/arbitrary
                                  code execution reachable from it, on any provider — see
                                  docs/security.md.
```

`backend/`, `frontend/`, and `ml/` are independently structured and testable. `ml/` never imports
FastAPI or `backend/`; training never runs inside a request handler — see
[docs/ml-pipeline.md](docs/ml-pipeline.md) for the ML data contract and methodology and
[docs/decisions.md](docs/decisions.md) ADR-001/015–045 for the Phase 5-10 design decisions.
Full architecture details: [docs/architecture.md](docs/architecture.md).

## Tech stack

- **Backend:** Python, FastAPI, SQLAlchemy + Alembic, Pydantic, Celery + Redis
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, TanStack Query, Zustand, React Hook Form + Zod, lightweight-charts
- **ML:** scikit-learn / XGBoost / PyTorch (LSTM, GRU), SHAP, Hugging Face Transformers (FinBERT — real sentiment inference, `ProsusAI/finbert`)
- **AI agent (Phase 8, multi-provider in 8.5):** Anthropic Claude, Groq, or Gemini — operator's
  choice via `LLM_PROVIDER` (`claude-haiku-4-5` by default, configurable) — via a vendor-agnostic
  `LLMProvider` abstraction requiring zero orchestrator changes per provider; structured
  tool-calling only (no vendor built-in tools), no vector DB (no long-form corpus exists to index;
  see ADR-030/034)
- **Data:** PostgreSQL, Redis
- **Infra:** Docker, Docker Compose, GitHub Actions

## Quick start

Requires Docker Desktop.

```bash
cp .env.example .env
cd infra
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000 (docs at `/docs`, health at `/health`, readiness at `/ready`)

Demo Mode (`DEMO_MODE=true` in `.env`, the default) uses `DemoMarketDataProvider` — synthetic,
deterministic price history for ~10 real, well-known tickers (never presented as real market
data — see [docs/decisions.md](docs/decisions.md) ADR-007) — so no external API keys are required.
Nothing is pre-seeded on startup; register an account, then trigger ingestion:

```bash
# 1. Register + log in via the UI (http://localhost:5173/register), or curl /api/v1/auth/register.
# 2. Promote that user to ANALYST or ADMIN — there's no self-service endpoint for this by design:
docker compose exec postgres psql -U alphalens -d alphalens -c \
  "UPDATE users SET role = 'ANALYST' WHERE email = 'you@example.com';"
# 3. Trigger ingestion (curl, or POST /api/v1/market-data/ingest from /docs):
curl -X POST http://localhost:8000/api/v1/market-data/ingest \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" -d '{}'
# 4. Poll GET /api/v1/jobs/{job_id} until "status": "COMPLETED", then browse Stock Explorer.
```

A `make seed` convenience (creating a demo user + triggering ingestion in one step) is a natural
Phase 4 addition once there's a UI reason to want one immediately on first run.

## Local development (without Docker)

Backend (requires a running PostgreSQL — see `DATABASE_URL` in `.env`):

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Backend tests also need a running PostgreSQL (`.env.test`, default `alphalens_test` on
`localhost:5432` — adjust `DATABASE_URL` if yours runs elsewhere, e.g. via
`DATABASE_URL=... pytest`) and build their schema directly from the ORM models rather than via
Alembic, for speed and isolation — see `backend/tests/conftest.py`.

Frontend:

```bash
cd frontend
npm install
npm run dev
```

ML package (standalone):

```bash
cd ml
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

## Common commands

| Command | Where | Purpose |
|---|---|---|
| `npm run lint` / `ruff check .` | frontend / backend, ml | Lint |
| `npm run typecheck` / `mypy app` | frontend / backend | Type check |
| `npm run test` / `pytest` | frontend / backend, ml | Run tests |
| `npm run build` | frontend | Production build |
| `alembic upgrade head` | backend | Apply DB migrations |

## Environment variables

See [.env.example](.env.example) for the full list with descriptions. Never commit a real `.env`.
The research agent (`POST /research/chat`) needs a real LLM credential to actually answer —
everything else in this project runs fully in Demo Mode with no external credentials, but the
agent is a real LLM integration and has no offline/demo substitute. `LLM_PROVIDER` picks which
vendor (`anthropic` default, or `groq`/`gemini`), and only that vendor's key is required:
`LLM_API_KEY` for Anthropic, `GROQ_API_KEY` for Groq, `GEMINI_API_KEY` for Gemini. Without the
selected provider's key, the endpoint returns a clean `503 AGENT_UNAVAILABLE` rather than failing
silently, falling back to a different provider, or faking a response.

## Documentation

- [docs/architecture.md](docs/architecture.md) — system design, request/data/inference/training flows
- [docs/database.md](docs/database.md) — schema
- [docs/api.md](docs/api.md) — API reference
- [docs/ml-pipeline.md](docs/ml-pipeline.md) — feature engineering, splitting, model comparison, registry
- [docs/security.md](docs/security.md) — auth, secrets, disclosures
- [docs/testing.md](docs/testing.md) — test strategy
- [docs/deployment.md](docs/deployment.md) — Docker/CI/CD, cloud deployment notes
- [docs/decisions.md](docs/decisions.md) — architecture decision records

Docs are filled in as their corresponding phase lands; unimplemented sections say so explicitly
rather than describing features that don't exist yet.

## License

See [LICENSE](LICENSE).
