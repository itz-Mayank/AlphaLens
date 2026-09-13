#!/bin/sh
# Render-specific container entrypoint (backend/Dockerfile.render only —
# infra/docker-compose.yml's dev image does not use this).
#
# Render's managed Postgres exposes its connection string as
# `postgres://...`/`postgresql://...`; this app's SQLAlchemy setup expects
# the psycopg3 driver scheme `postgresql+psycopg://` (see
# backend/app/core/config.py). Render's managed Key Value (Redis) gives one
# connection string for db 0; this app wants three separate logical Redis
# DBs (cache, Celery broker, Celery result backend — see .env.example).
# Rather than hand-rolling string surgery in `Settings` for a Render-only
# concern, rewrite the env vars here, once, before exec'ing the real
# command — the app itself stays deployment-target-agnostic.
set -e

eval "$(python3 - <<'PY'
import os
import re
from urllib.parse import urlsplit, urlunsplit

db_url = os.environ.get("DATABASE_URL", "")
if db_url and not db_url.startswith("postgresql+psycopg://"):
    db_url = re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", db_url)
    print(f"export DATABASE_URL={db_url!r}")

redis_url = os.environ.get("REDIS_URL", "")
if redis_url:
    parts = urlsplit(redis_url)
    broker = urlunsplit((parts.scheme, parts.netloc, "/1", "", ""))
    backend = urlunsplit((parts.scheme, parts.netloc, "/2", "", ""))
    print(f"export CELERY_BROKER_URL={broker!r}")
    print(f"export CELERY_RESULT_BACKEND={backend!r}")
PY
)"

exec "$@"
