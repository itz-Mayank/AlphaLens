"""Thin Redis JSON cache. Short, fixed TTLs — this is a read-through cache
for moderately-hot GET endpoints, not a source of truth and not invalidated
on write (see docs/decisions.md ADR-010): staleness is bounded by the TTL,
which is judged acceptable for data that only changes when an ingestion job
completes (at most a few times a day, not per-request).
"""

import json
from contextlib import suppress
from functools import lru_cache
from typing import Any, cast

import redis

from app.core.config import get_settings

STOCK_LIST_TTL_SECONDS = 60
STOCK_DETAIL_TTL_SECONDS = 30
STOCK_PRICES_TTL_SECONDS = 60
# The dashboard aggregates over every tracked security; same staleness
# rationale as the stock endpoints (ADR-010) but a slightly longer TTL
# since it's read far more often per user session (one dashboard load
# triggers the whole page) while changing even less often (only on
# ingestion) — see the Phase 4 ADR in decisions.md.
DASHBOARD_OVERVIEW_TTL_SECONDS = 90


@lru_cache
def get_redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def cache_get_json(key: str) -> Any | None:
    """Returns the cached value, or None on a cache miss OR if Redis is
    unreachable — caching must never turn a Redis outage into a user-facing
    500 (see docs/security.md's failure-handling notes)."""
    try:
        raw = get_redis_client().get(key)
    except redis.RedisError:
        return None
    if raw is None:
        return None
    # redis-py's sync/async overloads confuse mypy into inferring
    # Awaitable[Any] here; decode_responses=True guarantees a str at runtime.
    return json.loads(cast(str, raw))


def cache_set_json(key: str, value: Any, *, ttl_seconds: int) -> None:
    with suppress(redis.RedisError):
        get_redis_client().set(key, json.dumps(value), ex=ttl_seconds)
