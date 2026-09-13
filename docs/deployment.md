# Deployment, secrets, retention, and disaster recovery (Phase 10)

## Actual current deployment: Render

Unlike the AWS section below (a documented target architecture, not a real deployment), this
project **is** actually deployed via [Render](https://render.com) — see `render.yaml` at the repo
root, Render's Blueprint format. It provisions: a managed Postgres database, a managed Key Value
(Redis) instance, the backend API as a Docker web service, one Celery worker and one Celery beat
background worker (same image as the backend, different start command — `backend/Dockerfile.render`,
built from the repo root so it can bundle the sibling `ml/` package into the image, since Render
has no equivalent of docker-compose's dev-time bind mount), and the frontend as a static site build.

This mirrors the AWS target architecture's shape (backend/worker/beat, managed Postgres, managed
Redis) at a much smaller scale and cost, appropriate for a personal/demo deployment — it is not a
replacement for that document's AWS design if this project were ever run at real production scale;
see "What this deliberately does not use" below for why nothing fancier than either is justified yet.

Two things to know about this specific deployment:
- **Demo Mode by default.** `render.yaml` ships with `DEMO_MODE=true` and every real data-provider
  key (`TWELVE_DATA_API_KEY`, `FRED_API_KEY`, `GROQ_API_KEY`, etc.) left unset (`sync: false` —
  set only in the Render dashboard, never in this file). The deployed instance is fully functional
  on synthetic demo data with zero credentials; adding a real key later is additive, not a
  redeploy-from-scratch.
- **Render's free Postgres plan expires 30 days after creation** (then a 14-day grace period before
  Render deletes it, data included) — fine for an initial trial, not for anything meant to persist;
  upgrade the database's plan in the Render dashboard before relying on this deployment long-term.

## AWS target architecture

This section below is deliberately a **target architecture and operational policy**, not a record of
an actual deployment — no AWS resources have been created, and nothing here should be read as "this
is running in AWS." Where a step requires infrastructure or credentials this project doesn't have
(a real AWS account, an ACM certificate, a real secrets-manager instance), that is stated plainly
rather than implied.

## Target AWS architecture

A small, boring, understandable architecture on purpose — see "What this deliberately does not
use" below for why nothing fancier is justified at this project's scale.

```
Internet
   │
   ▼
Route 53 (DNS) ──► ACM (TLS certificate)
   │
   ▼
Application Load Balancer (HTTPS listener, terminates TLS)
   │
   ├──► ECS Fargate service: backend (FastAPI/uvicorn container)
   │        — target group health check: GET /ready (not /health — see
   │          docs/architecture.md's health/readiness split; a task that's
   │          up but can't reach its database should be pulled from
   │          rotation, not just "alive")
   │        — horizontal scaling on target-group request count / CPU
   │
   └──► S3 + CloudFront: frontend static build (`vite build`'s `dist/`)
            — the frontend Dockerfile's own `production` stage (nginx)
              is one valid alternative (an ECS/Fargate service instead of
              S3+CloudFront) if serving from the same account/VPC as the
              backend is preferred; both are legitimate, this just picks
              the cheaper one for a mostly-static SPA build

ECS Fargate service: worker (Celery worker container, `--concurrency`
tuned to task mix — see docs/decisions.md's Celery-hardening ADR)
   │
ECS Fargate service: beat (Celery Beat, exactly ONE running instance —
running two would double-fire the alert-evaluation/prediction-evaluation
schedule; ECS's `desiredCount: 1` on this service, not a scaling target,
enforces that)
   │
   ▼
ElastiCache for Redis (Celery broker + result backend + app cache —
the same three logical Redis DBs this project already uses locally,
just addressed at the ElastiCache endpoint instead of `redis:6379`)
   │
   ▼
RDS for PostgreSQL (Multi-AZ for production; automated backups — see
"Backup & disaster recovery" below)

ML artifacts (ml/experiments/registry.json + saved model directories)
   │
   ▼
EFS (mounted at the same `/ml/experiments` path the app already expects,
so `ML_REGISTRY_PATH`/`MODEL_STORAGE_PATH` need no code change) — chosen
over S3 specifically because `ml.registry.registry.ModelRegistry` reads/
writes the registry file with plain filesystem calls (`Path.read_text`/
`write_text`) and model `.save()`/`.load()` calls expect a real directory
tree; EFS is a POSIX filesystem an ECS task can mount directly, so this
requires zero code change. An S3-backed artifact store is a legitimate
future upgrade (see "What this deliberately does not use") but is not
built here since nothing in this codebase needs it yet.

CloudWatch Logs (container stdout/stderr — this project's existing
structlog JSON lines land there as-is) + CloudWatch Container Insights
(CPU/memory/task-count metrics ECS already emits for free)
```

### Why ECS Fargate, not Kubernetes/EKS

Three long-running services (backend, worker, beat) plus a scheduled scaling policy is exactly
what ECS Fargate is for, with no cluster to patch/upgrade and no separate control plane to pay for.
EKS would add a second orchestration model to learn and operate on top of Celery (which already
*is* this project's task-queue/scheduling layer) for no capability this project is missing. See
`docs/decisions.md`'s Phase 10 ADR.

### What this deliberately does not use

Kubernetes, Kafka, Spark, Airflow, MLflow, a vector database, a second message broker, or a second
relational database — none of Phase 10's requirements (production config safety, model promotion
gating, retraining, prediction logging/monitoring, drift detection, CI/CD, deployment
documentation) need any of them. PostgreSQL + Redis + Celery, already present, are sufficient; see
each relevant ADR in `docs/decisions.md` for the specific reasoning where one of these might look
tempting (e.g. "why not MLflow for the registry").

## AWS readiness (no AWS credentials required to verify this)

Every setting a production AWS deployment needs is already an environment variable this codebase
reads via `app/core/config.py::Settings` — RDS's connection string becomes `DATABASE_URL`,
ElastiCache's endpoint becomes `REDIS_URL`/`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`, the ALB's
real domain becomes `CORS_ORIGINS`/`FRONTEND_BASE_URL`. No AWS resource name, region, or ARN is
hardcoded anywhere in `backend/app` — grep for `arn:`/`amazonaws.com`/a hardcoded region returns
nothing. `ENVIRONMENT=production` triggers `app/core/config.py::validate_production_config`,
which refuses to start (`InsecureProductionConfigError`) if `JWT_SECRET`/`DATABASE_URL` still hold
their insecure local-dev defaults, `COOKIE_SECURE` is false, or `CORS_ORIGINS` still includes a
localhost/wildcard origin — verified by `tests/unit/test_production_config_safety.py` with zero
AWS credentials involved, exactly as this section requires. TLS itself terminates at the ALB (see
architecture diagram above); the application only ever needs to know it's being served over HTTPS
(`COOKIE_SECURE=true`) — it never needs a certificate of its own.

## Secrets management

Potential secrets in this system: `POSTGRES_PASSWORD`/`DATABASE_URL`'s credential, `JWT_SECRET`,
`GROQ_API_KEY`/`GEMINI_API_KEY`/`LLM_API_KEY`, and the Phase 10 provider-ecosystem credentials
`TWELVE_DATA_API_KEY`/`FRED_API_KEY` (`SEC_EDGAR_USER_AGENT` is not a secret — an identifying
contact string, not a credential — but is still sourced the same way, never hardcoded). None of
these live in source code, a Dockerfile, or the frontend today — every one is read from `Settings`
(environment variables only), `.env`/`.env.test` are both git-ignored, and `app/core/logging.py`'s
structured logging never logs a full request body or a settings dump (see `docs/security.md`'s
credential-handling section for the LLM-key-specific verification of this, and its "Provider
ecosystem credentials" section for the data-provider-specific one — including
`GET /api/v1/system/providers` reporting only a `credential_configured: bool`, never the value).

**Production secret source**: AWS Secrets Manager (or SSM Parameter Store for the non-sensitive
config like `CORS_ORIGINS`), injected into the ECS task definition as container environment
variables at task-start time via `secrets:` (Secrets Manager ARN references), never baked into the
container image or committed anywhere. This requires zero application code change — the app
already only ever reads `os.environ` via `pydantic-settings`; it has no idea whether a given
variable's value came from a `.env` file, an ECS task definition's plain `environment:` block, or
a `secrets:` block resolved from Secrets Manager at container start. No AWS Secrets Manager
credentials are required for (or used by) this project's local development or test suite — the
standard test suite runs entirely against `.env.test`'s local defaults, and the live-LLM tests
remain separately gated on the corresponding provider key being present in the environment (see
`docs/security.md`), never on any AWS-specific mechanism.

## Data retention

| Data | Retention policy | Why |
|---|---|---|
| `price_bars`, `news_articles`/`news_sentiment` | Indefinite | Historical price/news data is the actual research asset — deleting it would silently degrade every backtest/forecast that later needs a long lookback window. |
| `predictions` (Phase 10) | Indefinite | The live-performance-monitoring history (`prediction_service.get_live_performance`) gets *more* valuable over time, not less; there is no point at which an old prediction stops being useful evidence of real-world model performance. |
| `alert_events` | Indefinite | A user-facing history of what fired and when — a user's own record, not disposable telemetry. |
| `jobs` | Indefinite for now; a time-based archival policy (e.g. move `COMPLETED` rows older than 1 year to cold storage) is a reasonable future addition once volume actually justifies it — not built pre-emptively. |
| `audit_logs` | Indefinite, and specifically never auto-deleted by application code — a security audit trail that quietly expires defeats its own purpose. A compliance-driven retention *ceiling* (e.g. "purge after 7 years") is an operational/legal decision for whoever runs this in a regulated context, not something this codebase should decide unilaterally. |
| Model artifacts (`ml/experiments/*/models/`) | Every trained artifact is kept — `ARCHIVED`/`FAILED` registry records still point at real files, which is what makes `docs/decisions.md`'s promotion-gate ADR's audit trail ("what did we try, why was it rejected") actually inspectable later, not just a status string with nothing behind it. |

Nothing here is deleted "to reduce database size" — every table above is small at this project's
actual data volume (a handful of tracked securities, daily bars, one demo user base), so there is
no real storage-cost pressure yet; this table exists so a real pressure, if it ever arrives, has a
documented policy to extend rather than an ad-hoc one invented under pressure.

## Backup & disaster recovery

**Documented policy, not a tested drill** — see the explicit caveat at the end of this section.

- **PostgreSQL**: RDS's automated daily snapshots + point-in-time recovery (a standard RDS feature,
  not custom code) would be enabled with a retention window (e.g. 7-14 days) appropriate to how
  often this deployment's data actually changes. Locally/in Docker Compose, `postgres-data` is a
  named volume — `docker compose down` (without `-v`) preserves it; a manual `pg_dump`/`pg_restore`
  is the local-dev equivalent of a snapshot/restore.
- **Model artifacts**: EFS's own backup feature (AWS Backup integration) covers the mounted
  `ml/experiments` tree the same way RDS snapshots cover Postgres. Losing this would mean losing
  every non-`PRODUCTION` (`ARCHIVED`/`FAILED`) model's artifact and audit trail — the currently
  `PRODUCTION` model's own artifact is the only one inference actually depends on to keep serving.
- **Restore ordering**: Postgres restore first (registry-independent data — users, portfolios,
  price bars, predictions), then confirm the EFS-mounted registry/artifacts are present, then
  restart the backend/worker/beat services. `ml.inference.serving.load_forecast_models` fails
  cleanly (`ModelUnavailableError` → a clean 503) if the registry or an artifact is missing after a
  partial restore — the system degrades to "forecasts unavailable," not a crash loop.
- **Redis**: Deliberately treated as **disposable, not backed up**. The cache (`app/core/cache.py`)
  fails open by design (ADR-010) and would simply repopulate from Postgres on the next request. The
  Celery broker/result-backend DBs hold only in-flight task state — a Redis loss mid-task means
  that task's result is lost, but every task here is either safely re-triggerable (alert/prediction
  evaluation, both idempotent — see the Celery-hardening ADR) or was itself already recorded in the
  `jobs` table before being dispatched, so what was in flight is still visible as "stuck running"
  and can be manually re-triggered rather than silently disappearing.

**This has not been tested end-to-end** (no real RDS/EFS/AWS Backup exists for this project to
restore from) — the policy above is a documented, defensible plan, not a verified drill. Claiming
otherwise would violate this project's own "never claim untested E2E success" rule.
