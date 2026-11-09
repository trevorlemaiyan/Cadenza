# tests/test_health.py
"""
Smoke tests for the /health and /api/recommendations endpoints.
"""
import json


def test_health_returns_200(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_health_body_shape(client):
    r = client.get("/health")
    body = json.loads(r.data)
    assert "status" in body
    assert "postgres" in body
    assert "redis" in body


def test_health_postgres_connected(client):
    r = client.get("/health")
    body = json.loads(r.data)
    assert body["postgres"]["status"] == "connected"


def test_health_redis_status(client):
    """Redis status should report a valid state (connected or not_configured)."""
    r = client.get("/health")
    body = json.loads(r.data)
    assert body["redis"]["status"] in ("not_configured", "connected", "unavailable")


def test_api_recommendations_returns_200(client):
    r = client.get("/api/recommendations")
    assert r.status_code == 200


def test_api_recommend_alias_returns_200(client):
    r = client.get("/api/recommend")
    assert r.status_code == 200


def test_api_recommendations_has_cache_header(client):
    r = client.get("/api/recommendations")
    assert r.headers.get("X-Cache") in ("HIT", "MISS")


def test_api_recommendations_has_timing_header(client):
    r = client.get("/api/recommendations")
    timing = r.headers.get("X-Response-Time-Ms")
    assert timing is not None
    assert float(timing) >= 0


def test_api_recommendations_returns_list(client):
    r = client.get("/api/recommendations")
    body = json.loads(r.data)
    assert isinstance(body, list)


def test_api_recommendations_invalid_param(client):
    r = client.get("/api/recommendations?energy=not_a_number")
    assert r.status_code == 400


def test_index_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200


def test_login_redirects(client):
    """Login should redirect to Spotify (or return 302/500 when creds absent)."""
    r = client.get("/login")
    # 302 when credentials present, redirects to accounts.spotify.com
    # Allow any redirect or 500 (no creds configured in test env)
    assert r.status_code in (302, 500)
