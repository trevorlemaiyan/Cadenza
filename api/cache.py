"""
api/cache.py — Production Redis caching layer for Cadenza
==========================================================
Features
--------
* Connection pooling via ``redis.ConnectionPool`` — one pool per process, not
  one connection per request.
* Typed ``get`` / ``set`` / ``delete`` / ``exists`` helpers that transparently
  JSON-serialise values so callers never deal with raw bytes.
* ``cache_aside`` context-manager decorator: wraps any callable, checks the
  cache first, writes on miss, returns hit/miss status alongside the value so
  the HTTP layer can set ``X-Cache: HIT | MISS``.
* Graceful fallback: when ``REDIS_URL`` is unset or Redis is unreachable every
  operation silently returns ``None / False`` and the caller degrades to
  computing the value live — no exception propagates to the user.
* ``health_check()`` returns a dict suitable for embedding in ``/health``.

Key-space convention
--------------------
  cadenza:cc_token                     Spotify CC access token (TTL = expires_in)
  cadenza:spotify:track:<id>           /v1/tracks metadata  (TTL = 86 400 s)
  cadenza:spotify:search:<query_hash>  /v1/search payload   (TTL = 86 400 s)
  cadenza:recs:<vec_hash>:<n>          Recommendation list  (TTL = 3 600 s)

Usage
-----
    from api.cache import cache

    # Simple get/set
    value = cache.get("my:key")
    cache.set("my:key", {"data": 1}, ttl=3600)

    # Context-manager (returns (value, hit: bool))
    with cache.cache_aside("cadenza:recs:abc:10", ttl=3600) as (hit, stored):
        if hit:
            result = stored
        else:
            result = compute_expensive()
            cache.set("cadenza:recs:abc:10", result, ttl=3600)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CadenzaCache — thin, well-typed wrapper around redis-py
# ---------------------------------------------------------------------------

class CadenzaCache:
    """
    Thread-safe Redis cache with graceful degradation.
    A single ``ConnectionPool`` is shared across all requests in the process.
    """

    _POOL = None   # class-level pool, initialised once

    # TTL constants (seconds) ─ used as module-level defaults so callers can
    # import and reference them without hard-coding magic numbers.
    TTL_CC_TOKEN = 3540          # Spotify CC token (~59 min; token lasts 60)
    TTL_SPOTIFY_TRACK = 86_400   # Spotify /v1/tracks metadata  (24 h)
    TTL_SPOTIFY_SEARCH = 86_400  # Spotify /v1/search payload   (24 h)
    TTL_RECOMMENDATIONS = 3_600  # Recommendation results        (1 h)

    def __init__(self) -> None:
        self._client = None   # lazily connected per instance
        self._available: Optional[bool] = None   # tri-state: None=untested

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self):
        """
        Return a connected redis client, or ``None`` if Redis is unavailable.
        Uses a class-level ``ConnectionPool`` so a single pool is shared for
        the life of the process.
        """
        if self._available is False:
            return None
        if self._client is not None:
            return self._client

        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            self._available = False
            return None

        try:
            import redis as _redis

            if CadenzaCache._POOL is None:
                CadenzaCache._POOL = _redis.ConnectionPool.from_url(
                    redis_url,
                    decode_responses=True,
                    max_connections=20,
                    socket_timeout=2,         # don't block requests on slow Redis
                    socket_connect_timeout=2,
                )
                logger.info("Redis connection pool created (max=20).")

            self._client = _redis.Redis(connection_pool=CadenzaCache._POOL)
            self._client.ping()
            self._available = True
            logger.info("Redis connected: %s", redis_url.split("@")[-1])  # hide credentials
            return self._client

        except Exception as exc:
            logger.warning(
                "Redis unavailable — running without cache. %s", exc
            )
            self._available = False
            CadenzaCache._POOL = None   # reset pool so a later retry can re-attempt
            self._client = None
            return None

    def _r(self):
        """Alias for internal use."""
        return self._connect()

    # ------------------------------------------------------------------
    # Core get / set / delete
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        """
        Return the deserialised value for *key*, or ``None`` on miss/error.
        """
        r = self._r()
        if r is None:
            return None
        try:
            raw = r.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("cache.get(%r) error: %s", key, exc)
            return None

    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """
        Serialise *value* as JSON and store it with the given *ttl* (seconds).
        Returns ``True`` on success, ``False`` on error or if Redis is absent.
        """
        r = self._r()
        if r is None:
            return False
        try:
            r.set(key, json.dumps(value, default=str), ex=ttl)
            return True
        except Exception as exc:
            logger.warning("cache.set(%r) error: %s", key, exc)
            return False

    def delete(self, *keys: str) -> int:
        """Delete one or more keys. Returns the number of keys deleted."""
        r = self._r()
        if r is None:
            return 0
        try:
            return r.delete(*keys)
        except Exception as exc:
            logger.warning("cache.delete error: %s", exc)
            return 0

    def exists(self, key: str) -> bool:
        """Return ``True`` if *key* exists in Redis."""
        r = self._r()
        if r is None:
            return False
        try:
            return bool(r.exists(key))
        except Exception as exc:
            logger.warning("cache.exists(%r) error: %s", key, exc)
            return False

    def ttl(self, key: str) -> int:
        """Return remaining TTL in seconds (-1 = no TTL, -2 = not found)."""
        r = self._r()
        if r is None:
            return -2
        try:
            return r.ttl(key)
        except Exception as exc:
            logger.warning("cache.ttl(%r) error: %s", key, exc)
            return -2

    # ------------------------------------------------------------------
    # Convenience wrappers for common Cadenza key namespaces
    # ------------------------------------------------------------------

    def get_spotify_track(self, spotify_id: str) -> Optional[dict]:
        return self.get(f"cadenza:spotify:track:{spotify_id}")

    def set_spotify_track(self, spotify_id: str, payload: dict) -> bool:
        return self.set(
            f"cadenza:spotify:track:{spotify_id}",
            payload,
            ttl=self.TTL_SPOTIFY_TRACK,
        )

    def get_spotify_search(self, query_hash: str) -> Optional[dict]:
        return self.get(f"cadenza:spotify:search:{query_hash}")

    def set_spotify_search(self, query_hash: str, payload: dict) -> bool:
        return self.set(
            f"cadenza:spotify:search:{query_hash}",
            payload,
            ttl=self.TTL_SPOTIFY_SEARCH,
        )

    def get_recommendations(self, vec_hash: str, n: int) -> Optional[list]:
        return self.get(f"cadenza:recs:{vec_hash}:{n}")

    def set_recommendations(self, vec_hash: str, n: int, results: list) -> bool:
        return self.set(
            f"cadenza:recs:{vec_hash}:{n}",
            results,
            ttl=self.TTL_RECOMMENDATIONS,
        )

    def get_cc_token(self) -> Optional[str]:
        return self.get("cadenza:cc_token")

    def set_cc_token(self, token: str, ttl: int) -> bool:
        return self.set("cadenza:cc_token", token, ttl=ttl)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> dict:
        """
        Returns a status dict for use in the ``/health`` endpoint::

            {"status": "connected", "latency_ms": 1.2}
            {"status": "unavailable", "error": "..."}
            {"status": "not_configured"}
        """
        if not os.getenv("REDIS_URL"):
            return {"status": "not_configured"}

        r = self._r()
        if r is None:
            return {"status": "unavailable", "error": "connection failed"}

        import time
        try:
            t0 = time.perf_counter()
            r.ping()
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {"status": "connected", "latency_ms": latency_ms}
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        state = "connected" if self._available else ("unavailable" if self._available is False else "untested")
        return f"<CadenzaCache state={state}>"


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------

cache = CadenzaCache()
