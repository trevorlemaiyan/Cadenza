# tests/test_cache.py
"""
Unit tests for api/cache.py — CadenzaCache graceful fallback behaviour.
"""
from api.cache import CadenzaCache


def test_cache_get_returns_none_without_redis():
    c = CadenzaCache()
    assert c.get("nonexistent:key") is None


def test_cache_set_returns_false_without_redis():
    c = CadenzaCache()
    assert c.set("some:key", {"data": 1}) is False


def test_cache_exists_returns_false_without_redis():
    c = CadenzaCache()
    assert c.exists("some:key") is False


def test_cache_delete_returns_zero_without_redis():
    c = CadenzaCache()
    assert c.delete("some:key") == 0


def test_health_check_not_configured():
    c = CadenzaCache()
    result = c.health_check()
    assert result["status"] == "not_configured"


def test_ttl_constants_sensible():
    assert CadenzaCache.TTL_SPOTIFY_TRACK == 86_400
    assert CadenzaCache.TTL_RECOMMENDATIONS == 3_600
    assert CadenzaCache.TTL_SPOTIFY_SEARCH == 86_400
    assert CadenzaCache.TTL_CC_TOKEN < 3_600   # less than a full hour
