# API Reference

## Status

Reflects Phase 8. The full live schema (request/response bodies, validation rules) is always
authoritative at `/docs` (Swagger) and `/redoc` on the running backend — this file is a map of
what exists and why, not a copy of the OpenAPI spec.

Every error response has the shape `{"error": {"code": "...", "message": "..."}}` — see
[security.md](security.md).

## Infrastructure probes (unauthenticated, outside `/api/v1`)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness — no I/O, always `{"status": "ok"}` once the process is up. |
| GET | `/ready` | Readiness — live `SELECT 1` against Postgres. |

## Auth (`/api/v1/auth`) — Phase 2

| Method | Path | Auth | Rate limit | Description |
|---|---|---|---|---|
| POST | `/auth/register` | none | 10/hour | Create account, returns access token + sets refresh cookie. |
| POST | `/auth/login` | none | 10/minute | Returns access token + sets refresh cookie. |
| POST | `/auth/refresh` | refresh cookie | 30/minute | Rotates the refresh token, returns a new access token. |
| POST | `/auth/logout` | refresh cookie | — | Revokes the session, clears the cookie. Idempotent. |
| POST | `/auth/forgot-password` | none | 5/hour | Always `204`, regardless of whether the email exists. |
| POST | `/auth/reset-password` | reset token (body) | 10/hour | Consumes the token, revokes all sessions for that user. |

## Users (`/api/v1/users`) — Phase 2

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/users/me` | bearer | Current user's profile. |
| PATCH | `/users/me` | bearer | Update `full_name`. |
| POST | `/users/me/change-password` | bearer | Revokes all other sessions on success. |
| DELETE | `/users/me` | bearer + password in body | Deletes the account. Audit trail survives (ADR-006). |

## Stocks (`/api/v1/stocks`) — Phase 3

All require a bearer token. Responses cached in Redis with short TTLs (ADR-010) — a field always
present in every response, `data_source`, is `"demo"` for every security today (ADR-007).

| Method | Path | Description |
|---|---|---|
| GET | `/stocks` | Paginated list. Query: `q` (ticker/name substring), `sector`, `limit` (≤100), `offset`. Each item includes a computed quote (`last_price`, `change`, `change_percent`, `volume`, `as_of`) from the two most recent price bars. |
| GET | `/stocks/{ticker}` | Detail: security info + quote + `week_52_high`/`week_52_low` (computed over the trailing 365 days of bars). `404 STOCK_NOT_FOUND` if never ingested. |
| GET | `/stocks/{ticker}/prices` | OHLCV history, ascending by time. Query: `range` = `1M`\|`3M`\|`6M`\|`1Y`\|`5Y`\|`MAX` (default `1Y`), filtered relative to wall-clock "now". |

## Market data (`/api/v1/market-data`) — Phase 3

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/market-data/ingest` | ANALYST or ADMIN only | Body: `{tickers?: string[], start_date?, end_date?}` (omit `tickers` for the full known universe; omit dates for the last ~2 years through today). Returns `202 {job_id, status: "QUEUED"}` immediately — ingestion runs in a Celery worker. Re-running with the same window is idempotent (upsert on `(security_id, ts)`, not append). |

A plain `USER` gets `403 FORBIDDEN` — this is the one RBAC-gated endpoint that exists today,
proving `require_roles()` (built in Phase 2, unused until now) actually works in a live request.

## Jobs (`/api/v1/jobs`) — Phase 3

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/jobs/{id}` | bearer | Status of any job (currently only `MARKET_DATA_INGESTION`). `metadata` carries type-specific detail — for ingestion: tickers requested, unknown tickers, date range, and per-ticker fetched/written/rejected counts. `404 JOB_NOT_FOUND` for an unknown id. |

Generic by design (ADR-009) — later job types (training, backtests, news processing, reports)
reuse this same endpoint rather than each getting their own.

## Dashboard (`/api/v1/dashboard`) — Phase 4

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/dashboard/overview` | bearer (any role) | Market summary, movers, sector performance, breadth, and recent activity — see `app/services/dashboard_service.py` for the exact methodology behind every figure. One cache entry (90s TTL) serves every viewer; not user-specific. |

Response shape (all five sections always present, even with zero ingested data — see "Empty-data
behavior" below):

- **`market_summary`** — `total_securities`, `securities_with_price_data`, `latest_market_data_ts`,
  `data_sources` (distinct values present, e.g. `["demo"]`), `freshness_status`
  (`current`/`stale`/`outdated`/`no_data` — thresholds: ≤3 days old = current, ≤14 = stale, else
  outdated).
- **`market_movers`** — `as_of` (the shared reference date, see ADR-012), `top_gainers`/
  `top_losers` (top 5 by daily return, `null` return excluded — never ranked as 0%), `most_active`
  (top 5 by volume).
- **`sector_overview`** — per sector actually present in `securities` (never an invented list):
  `security_count` (tracked), `securities_with_data` (as of the reference date),
  `average_return_percent` (equal-weighted mean, `null` if no security in that sector has a
  defined return as of the reference date).
- **`market_breadth`** — `status: "ok"` with `advancing`/`declining`/`unchanged`/`no_data` counts,
  or `status: "unavailable"` (with the count fields `null`) when no security has two consecutive
  days of history as of the same date.
- **`recent_activity`** — up to 10 most-recently-updated securities (by each security's own latest
  bar, *not* reference-date-filtered — this section answers "what changed recently," not "what
  moved on the reference date").

**Daily return formula** (the one used everywhere a return appears, per ADR-013):
`(close_t / close_{t-1} - 1) * 100`, from a security's two most recent bars. `null` — never `0` —
when there's no previous bar, or it's exactly zero.

**Empty-data behavior:** before any ingestion, this endpoint still returns `200` with a fully
honest empty shape (`freshness_status: "no_data"`, `market_breadth.status: "unavailable"`, empty
lists) — never a `404` or fabricated zeros standing in for "nothing measured yet."

## Forecast (`/api/v1/stocks/{ticker}`) — Phase 6

Real inference from the registered XGBoost models (`ml.inference`) — never a hardcoded value, and
never trains anything (ADR-001). See [ml-pipeline.md](ml-pipeline.md) "Inference serving" for the
full data-environment disclosure this endpoint always carries.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/stocks/{ticker}/forecast` | bearer | Combined return + direction forecast for the 5-day horizon. |
| GET | `/stocks/{ticker}/forecast/explanation` | bearer | SHAP top-factor explanation for the direction prediction. Query: `top_n` (default 5, max = feature count). Materially more expensive than `/forecast` — a separate call, never computed as a side effect of it. |

`/forecast` response: `ticker`, `model_name` (`"xgboost"`), `return_model_version`,
`direction_model_version`, `feature_version`, `dataset_version`, `horizon_days`,
`predicted_direction` (`Bearish`/`Neutral`/`Bullish`), `expected_return`, `probabilities` (per
class, only present because the direction model genuinely supports `predict_proba` — never
fabricated for a model that doesn't), `prediction_timestamp`, `data_timestamp`, `data_source`
(`"demo"`/`"external"` — **always check this**: a forecast computed from demo/synthetic price data
has no real predictive meaning), `disclaimer`.

`/forecast/explanation` response: `ticker`, `predicted_direction`, `model_version`,
`feature_version`, `as_of`, `top_direction_factors`/`top_return_factors` (each
`{feature, value, contribution, direction}`), `data_source`, `methodology_note` ("SHAP explains
... it does not establish causality").

Error responses (all `{"error": {"code": "...", "message": "..."}}`):

| Code | Status | Meaning |
|---|---|---|
| `STOCK_NOT_FOUND` | 404 | Ticker unknown to this deployment's own `securities` table. |
| `UNSUPPORTED_TICKER` | 422 | Ticker is known, but not in the registered model's trained universe (11 research tickers). |
| `INSUFFICIENT_HISTORY` | 422 | Fewer than 60 trading days of price history, or the most recent day's features aren't fully warmed up. |
| `DATA_VALIDATION_FAILED` | 422 | The ticker's price history failed `ml.data.validation.validate`. |
| `MODEL_UNAVAILABLE` | 503 | No registered, evaluated model exists yet — a real, expected state before any training run. |

## Research (`/api/v1/research`) — Phases 6 & 8

Research-only endpoints, not part of the core dashboard/stock-detail surface.

| Method | Path | Auth | Rate limit | Description |
|---|---|---|---|---|
| POST | `/research/backtest` | bearer | — | Runs `ml.backtest`'s portfolio engine against the registered models' historical predictions. |
| POST | `/research/chat` | bearer | 20/hour | The grounded research agent (Phase 8) — see below. |

Request body: `tickers` (1–20), `start_date`, `end_date`, `commission_bps` (default 5),
`slippage_bps` (default 5), `initial_capital` (default 100,000), `max_position_weight` (optional
cap per name). Response: `tickers`, date range, model/feature/dataset versions,
`equity_curve` (`[{ts, equity, benchmark_equity}]`), `metrics` (see
[ml-pipeline.md](ml-pipeline.md) "Portfolio backtest methodology" for every field's definition),
`num_rebalance_events`, `data_sources` (every distinct `data_source` among the requested tickers —
never hidden), `disclaimer`. Same error codes as `/forecast` above, plus `TOO_MANY_TICKERS` (422,
>20 tickers) and `VALIDATION_ERROR` (422, e.g. `end_date <= start_date`).

### `POST /research/chat` (Phase 8)

The grounded research agent — an LLM reasoning layer over AlphaLens's existing structured data via
9 controlled tools (`app/agent/tools.py`), never a general-purpose chatbot and never a source of
data itself. See [architecture.md](architecture.md) "Research agent flow" for the full
request→tool→evidence→response loop and [security.md](security.md) for the prompt-injection,
non-autonomy, and conversation-isolation guarantees.

Request body: `message` (1–2000 chars), `conversation_id` (optional — omit to start a new
conversation; the response echoes back the id to use, or a newly generated one, for the next turn).

Response (`ChatResponse`):

| Field | Meaning |
|---|---|
| `conversation_id` | Pass this back on the next turn to continue the same bounded conversation. |
| `answer` | The final natural-language answer only — never chain-of-thought or internal reasoning. |
| `evidence` | `[{source_type, source_id, ticker, timestamp, data, provenance}]` — every tool result that grounded this answer, one entry per fact retrieved. `source_type` is one of `MARKET_DATA`/`FORECAST`/`SHAP`/`NEWS`/`SENTIMENT`/`BACKTEST`. |
| `citations` | Deduplicated, sorted display tags (`"[Forecast]"`, `"[SHAP]"`, `"[Market Data]"`, ...) — every evidence source type used, matching the inline tags the agent is instructed to cite. |
| `tools_used` | Deduplicated, sorted tool names that succeeded (a failed tool call is never credited here). |
| `tool_calls` | `[{name, ok, latency_ms}]` for every tool call attempted this turn, including failed ones — operational metadata only, never the LLM's reasoning. |
| `model` / `provider` | Which model/provider actually answered — this deployment's configured `LLM_PROVIDER` (`"anthropic"`/`"groq"`/`"gemini"`, e.g. `"claude-haiku-4-5-20251001"` / `"anthropic"`) — never hidden. |
| `request_id` | For correlating with server-side logs (see [security.md](security.md) "Observability"). |
| `prompt_version` | The static system prompt's version (`"v1"` today) — bumped on any behavioral change to the prompt. |
| `disclaimer` | Standard "analytical and educational only, not financial advice" text. |

Error responses:

| Code | Status | Meaning |
|---|---|---|
| `AGENT_UNAVAILABLE` | 503 | No LLM provider configured (`LLM_API_KEY` unset — a real, expected dev state, never a silent fallback), or the provider/orchestrator failed (timeout, provider error, too-long/empty message). |
| `VALIDATION_ERROR` | 422 | `message` is empty or exceeds 2000 characters. |

A plain-text request body containing what looks like an instruction (e.g. embedded in a pasted
news excerpt) is still just the `message` field's content — the agent's own defenses against
treating retrieved *tool* content as instructions are documented in
[security.md](security.md) and don't change how this endpoint is called.

## News (`/api/v1/stocks/{ticker}`, `/api/v1/news`) — Phase 7

Real news articles and FinBERT sentiment (`ml.nlp.sentiment`) — never fabricated. See
[ml-pipeline.md](ml-pipeline.md) "News & sentiment pipeline" for the full provider/entity-mapping/
aggregation methodology and ADR-025/026/028 for the licensing, entity-mapping, and demo-provider
design decisions.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/stocks/{ticker}/news` | bearer | Recent articles mapped to this security. Query: `limit` (default 20, max 100). |
| GET | `/stocks/{ticker}/sentiment` | bearer | Current 24-hour and 7-day sentiment aggregates + momentum. |
| GET | `/stocks/{ticker}/sentiment/history` | bearer | Daily sentiment aggregates, oldest first (chart-ready). Query: `days` (default 30, max 90). |
| POST | `/news/ingest` | ANALYST or ADMIN only | Body: `{tickers?: string[], since?: datetime}` (omit `tickers` for the full known universe; omit `since` for the last 7 days through now). Returns `202 {job_id, status: "QUEUED"}` — fetch/normalize/entity-match/FinBERT-sentiment all run in the Celery worker, never in this request. |

`/news` response: `ticker`, `articles` (`[{id, title, summary, url, publisher, published_at,
data_source, sentiment}]` — `sentiment` is `null`, not fabricated, if the ingestion pipeline
hasn't scored that article yet), `data_sources` (every distinct `data_source` among the returned
articles — `"demo"` today, since no real provider is configured; never hidden — see ADR-023's
disclosure precedent extended here).

`/sentiment` response: `ticker`, `last_24h`/`last_7d` (each `{as_of, window_days, since, until,
article_count, positive_count, neutral_count, negative_count, average_sentiment_score,
sentiment_momentum}`), `model_version`, `disclaimer` ("Sentiment is an informational signal ... not
a guaranteed trading signal ... has not been shown to predict this security's future return").

`/sentiment/history` response: `ticker`, `points` (`[{date, article_count, positive_count,
neutral_count, negative_count, average_sentiment_score}]`, oldest first), `model_version`.

Error responses reuse the same codes as `/forecast` where applicable (`STOCK_NOT_FOUND` 404 for an
unticked ticker); an empty result (no news yet, no sentiment yet) is always a `200` with empty/
`null`/zero fields, never a `404` — "no news yet" is a real, expected state, not an error.
