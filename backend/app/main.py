from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.rate_limit import limiter

settings = get_settings()
configure_logging(settings.log_level)


def create_app() -> FastAPI:
    app = FastAPI(
        title="AlphaLens API",
        description=(
            "AI-powered market intelligence, forecasting, research, and portfolio analytics. "
            "Provides analytical and educational information only — not financial advice."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # No explicit RateLimitExceeded handler is registered: it already
    # subclasses Starlette's HTTPException, so register_exception_handlers'
    # generic HTTPException handler wraps it in the app's standard
    # {"error": {"code", "message"}} envelope with the real rate-limit
    # detail intact. slowapi's own default handler returns a bare
    # {"error": "<string>"} instead, which breaks every client's error
    # parsing (api-client.ts reads `error.code`/`error.message`, both
    # undefined on a plain string) — registering it here previously
    # silently dropped the real "N per M" message behind a generic
    # "UNKNOWN_ERROR" on every rate-limited endpoint, not just the
    # research agent.
    app.state.limiter = limiter
    register_exception_handlers(app)

    app.include_router(api_router)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Liveness probe — process is up. Does not check dependencies."""
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    def ready(response: Response) -> dict:
        """Readiness probe — checks the dependencies actually necessary to
        serve traffic, distinct from `/health`'s "process is up" liveness
        check. PostgreSQL is fatal (returns 503) since every request needs
        it. Redis is reported but never fatal: `app/core/cache.py` fails
        open on a Redis outage (a cache miss, not a 500) and
        `app/core/rate_limit.py`'s limiter is in-memory — neither actually
        blocks synchronous request serving. A Redis outage does degrade
        Celery task dispatch (ingestion/alerts/predictions/retraining),
        which is why it's still surfaced here rather than silently
        ignored, just not treated as "not ready to serve HTTP traffic."
        Returns an actual 503 status code when unavailable — not just a
        200 with an "unavailable" string in the body, which an
        orchestrator's HTTP-status-based readiness check would otherwise
        never see.
        """
        import redis as redis_lib
        from sqlalchemy import text

        from app.core.cache import get_redis_client
        from app.db.session import engine

        checks: dict[str, str] = {}
        healthy = True

        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001 — readiness must report any failure
            checks["database"] = f"unavailable: {exc}"
            healthy = False

        try:
            get_redis_client().ping()
            checks["redis"] = "ok"
        except redis_lib.RedisError as exc:
            checks["redis"] = f"unavailable: {exc}"

        response.status_code = 200 if healthy else 503
        return {"status": "ok" if healthy else "unavailable", "checks": checks}

    return app


app = create_app()
