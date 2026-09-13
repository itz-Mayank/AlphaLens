from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    demo_mode: bool = True
    # Phase 10 provider ecosystem: independent, explicit provider
    # selection per data type — never derived from `demo_mode` (which
    # predates this and is kept only for the handful of non-provider
    # things still keyed on it, e.g. the email provider). `DATA_ENVIRONMENT`
    # is informational/labeling only (surfaced in provider health output),
    # never itself a selector — the four `*_PROVIDER` settings below are
    # each independently authoritative for their own provider type. See
    # docs/decisions.md's Phase 10 provider-ecosystem ADR.
    data_environment: str = "demo"
    market_data_provider: str = "demo"
    news_provider: str = "demo"
    fundamentals_provider: str = "none"
    macro_provider: str = "none"

    database_url: str = "postgresql+psycopg://alphalens:alphalens@localhost:5432/alphalens"

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    # True executes Celery tasks synchronously in-process (no broker/worker
    # needed) — set in .env.test so API tests can exercise the real
    # ingestion task without standing up Redis + a worker process.
    celery_task_always_eager: bool = False

    # Reserved for a real MarketDataProvider (unused while
    # MARKET_DATA_PROVIDER=demo — see app/providers/market_data/__init__.py).
    market_data_api_key: str = ""
    # Reserved for a real NewsProvider (unused while NEWS_PROVIDER=demo —
    # see app/providers/news/__init__.py).
    news_api_key: str = ""

    # Twelve Data (Phase 10 real MarketDataProvider candidate — selected
    # over Alpha Vantage [25 req/day, impractical] and Finnhub [historical
    # OHLCV moved to paid tiers] — see docs/decisions.md's Phase 10
    # provider-ecosystem ADR). No default: unset means the provider fails
    # loudly if selected without a key, never a silent fallback.
    twelve_data_api_key: str = ""

    # SEC EDGAR (Phase 10 FundamentalsProvider — no API key required, only
    # an identifying User-Agent per SEC's fair-access policy). The default
    # below is a real, working identification string but should be
    # replaced with this deployment's own contact address in production —
    # see docs/decisions.md's Phase 10 provider-ecosystem ADR.
    sec_edgar_user_agent: str = "AlphaLens research alphalens-dev@example.com"

    # FRED (Phase 10 MacroDataProvider — free, public-domain, but requires
    # a registered API key this deployment does not have configured by
    # default). No default: unset means the provider fails loudly if
    # selected without a key.
    fred_api_key: str = ""

    jwt_secret: str = "insecure-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    password_reset_token_expire_minutes: int = 30
    refresh_cookie_name: str = "alphalens_refresh_token"
    cookie_secure: bool = False

    frontend_base_url: str = "http://localhost:5173"

    cors_origins: str = "http://localhost:5173"

    model_storage_path: str = "/data/model_artifacts"
    feature_set_version: str = "fs_v1"
    # Path to the ml/ package's model registry file, produced by
    # `ml/scripts/run_real_experiment.py` — `/ml` is where docker-compose
    # bind-mounts the sibling `ml/` project directory (see
    # infra/docker-compose.yml); local (non-Docker) dev/test overrides this
    # via .env/.env.test to the real relative path. A missing file here is
    # a real, expected state (no training run yet) — see
    # `ml.inference.serving.ModelUnavailableError`, mapped to a clean 503.
    ml_registry_path: str = "/ml/experiments/registry.json"
    report_storage_path: str = "/data/reports"

    log_level: str = "INFO"

    # Research agent (Phase 8) — see app/agent/llm_provider.py. No default
    # key: an unset LLM_API_KEY is a real, expected dev state (raises a
    # clean LLMProviderError, mapped to a 503), never a silent fallback.
    # claude-haiku-4-5 is the deliberately cost-conscious default dev
    # model — see docs/decisions.md's LLM-provider ADR for why.
    llm_api_key: str = ""
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_timeout_seconds: float = 30.0
    llm_max_tool_iterations: int = 6
    llm_max_tool_calls_per_turn: int = 4

    # Multi-provider validation (Phase 8.5) — see app/agent/llm_provider.py.
    # LLM_PROVIDER selects which concrete LLMProvider `get_llm_provider()`
    # builds; default "anthropic" keeps every pre-8.5 deployment's behavior
    # unchanged (LLM_API_KEY alone is still sufficient). Switching to "groq"
    # or "gemini" requires that provider's own key below — never a silent
    # fallback to a different provider than the one requested.
    llm_provider: str = "anthropic"
    # No default model pin: Groq's model lineup changes faster than a
    # released model stays supported (see docs/decisions.md's provider ADR)
    # — openai/gpt-oss-20b is today's cost-conscious, tool-calling-capable
    # default, but GROQ_LLM_MODEL should be checked against
    # console.groq.com/docs/models periodically, not treated as permanent.
    groq_api_key: str = ""
    groq_llm_model: str = "openai/gpt-oss-20b"
    # "gemini-flash-latest" is Google's own auto-updating alias for the
    # current Flash-tier model — deliberately chosen over a dated version
    # string (e.g. "gemini-2.5-flash") specifically so this default doesn't
    # silently start 404ing on that model's deprecation date.
    gemini_api_key: str = ""
    gemini_llm_model: str = "gemini-flash-latest"

    # Alerts (Phase 9) — see app/workers/tasks/alerts.py. Celery Beat's
    # smallest production-appropriate scheduling primitive: one periodic
    # task, no new queueing system. 5 minutes matches this deployment's
    # daily-bar price data (nothing meaningfully changes faster than that
    # in Demo Mode) while staying responsive enough for a demo.
    alert_evaluation_interval_seconds: int = 300

    # Predictions (Phase 10) — see app/workers/tasks/predictions.py. Daily:
    # price bars in this deployment only update once a day (Demo Mode's
    # daily-bar ingestion), so checking maturity more often finds nothing
    # new.
    prediction_evaluation_interval_seconds: int = 86_400

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


_INSECURE_JWT_SECRET = "insecure-dev-secret-change-me"
_INSECURE_POSTGRES_PASSWORD = "changeme_local_dev_only"


class InsecureProductionConfigError(RuntimeError):
    """Raised at startup — never at request time — when `ENVIRONMENT=production`
    is combined with a setting that is only safe in development/test. This
    is Phase 10's "production must fail safely when required
    secrets/configuration are missing" rule: refusing to start with an
    insecure config is safer than starting anyway and silently running
    production traffic over a known-default JWT secret, an
    HTTP-only cookie, or a wildcard CORS origin.
    """


def validate_production_config(settings: Settings) -> None:
    if settings.environment != "production":
        return

    problems: list[str] = []
    if settings.jwt_secret == _INSECURE_JWT_SECRET:
        problems.append(
            "JWT_SECRET is still the insecure development default — set a long, random "
            "secret via the environment/secret manager."
        )
    if _INSECURE_POSTGRES_PASSWORD in settings.database_url:
        problems.append(
            "DATABASE_URL still contains the insecure development default password."
        )
    if not settings.cookie_secure:
        problems.append(
            "COOKIE_SECURE must be true in production (refresh cookies require HTTPS)."
        )
    _dev_origins = ("*", "http://localhost:5173", "http://localhost:3000")
    if any(origin in _dev_origins for origin in settings.cors_origin_list):
        problems.append(
            "CORS_ORIGINS still includes a wildcard or a localhost dev origin — set it to "
            "the real production frontend origin(s) only."
        )
    # Deliberately NOT a problem: DEMO_MODE=true in production is a valid,
    # supported deployment shape for this project (a publicly-hosted demo
    # showcasing the architecture with synthetic data, clearly labeled as
    # such throughout the API/UI — see ADR-007) — never forced to false
    # just because ENVIRONMENT=production.

    if problems:
        raise InsecureProductionConfigError(
            "Refusing to start with ENVIRONMENT=production and an insecure configuration:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    validate_production_config(settings)
    return settings
