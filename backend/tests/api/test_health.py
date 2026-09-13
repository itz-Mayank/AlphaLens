"""Tests for /health (liveness) vs /ready (readiness) — Phase 10's
explicit requirement that the two behave differently: liveness never
depends on external dependencies, readiness does and must report a real
503 (not just a 200 with an "unavailable" string an HTTP-status-based
orchestrator check would never see).
"""

from unittest.mock import patch

from app.db.session import engine


def test_health_returns_ok_and_never_touches_the_database(client):
    with patch.object(engine, "connect", side_effect=RuntimeError("db is down")):
        res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_ready_returns_ok_when_the_database_is_reachable(client):
    res = client.get("/ready")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"


def test_ready_returns_a_real_503_when_the_database_is_unreachable(client):
    with patch.object(engine, "connect", side_effect=RuntimeError("connection refused")):
        res = client.get("/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unavailable"
    assert "connection refused" in body["checks"]["database"]


def test_ready_reports_redis_but_a_redis_outage_alone_is_not_fatal(client):
    """Cache reads/writes fail open and the rate limiter is in-memory —
    neither actually needs Redis to serve a request, so a Redis-only
    outage must not flip readiness to unavailable."""
    import redis

    def _broken_client():
        raise redis.RedisError("redis down")

    with patch("app.core.cache.get_redis_client", side_effect=_broken_client):
        res = client.get("/ready")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert "redis down" in body["checks"]["redis"]
