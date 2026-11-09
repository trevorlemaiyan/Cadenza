"""
api/recommender.py — Hybrid Music Recommendation Engine
========================================================
Algorithm
---------
1. Build a 6-D feature vector for each track in the PostgreSQL Track table.
2. Compute cosine similarity between a *seed* vector and every track in the
   corpus, returning the top-N closest matches.
3. For each result, fetch fresh metadata (name, artist, album_art_url) from
   Spotify's /v1/tracks endpoint using a *Client-Credentials* token (no user
   login required).  Falls back to cached DB metadata gracefully when:
     • No Spotify credentials are configured.
     • The Spotify API rate-limits us (HTTP 429).
     • Any network error occurs.

Caching (all via api/cache.py → Redis)
---------------------------------------
  cadenza:cc_token                     Spotify CC token      (TTL ≈ 59 min)
  cadenza:spotify:track:<spotify_id>   /v1/tracks metadata   (TTL = 24 h)
  cadenza:recs:<vec_hash>:<n>          Recommendation list   (TTL = 1 h)

Feature vector dimensions (all in [0, 1])
------------------------------------------
  [0] tempo / 250        (raw BPM normalised)
  [1] energy
  [2] danceability
  [3] valence
  [4] acousticness
  [5] instrumentalness

Return value of get_recommendations
------------------------------------
    results, cache_hit = get_recommendations(seed_vector, n)

``cache_hit`` is True when the full result set was served from Redis without
touching PostgreSQL or Spotify — used by the HTTP layer to set X-Cache headers.

Usage
-----
    from api.recommender import get_recommendations, vector_from_top_tracks

    results, cache_hit = get_recommendations(
        seed_vector=[0.5, 0.8, 0.7, 0.6, 0.1, 0.0],
        n=10,
    )
    # results → list[dict] with keys:
    #   spotify_id, name, artist, genre, album_art_url, similarity_pct
    # cache_hit → bool
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Optional

import numpy as np
import requests
from sklearn.metrics.pairwise import cosine_similarity as sk_cosine_sim

# ---------------------------------------------------------------------------
# Cache singleton (graceful no-op when Redis is absent)
# ---------------------------------------------------------------------------
from api.cache import cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process fallback caches (used when Redis is absent)
# ---------------------------------------------------------------------------
_cc_token_cache: dict = {}
_recs_fallback_cache: dict = {}


# ---------------------------------------------------------------------------
# Spotify Client-Credentials token
# ---------------------------------------------------------------------------

def _get_cc_token() -> Optional[str]:
    """
    Return a valid Spotify Client-Credentials access token.
    Order of precedence:
      1. Redis cache  (cadenza:cc_token)
      2. In-process dict fallback
      3. Fresh fetch from accounts.spotify.com
    """
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    # 1 — Redis
    cached = cache.get_cc_token()
    if cached:
        return cached

    # 2 — in-process dict (used when Redis is absent)
    if _cc_token_cache.get("token") and _cc_token_cache.get("exp", 0) > time.time():
        return _cc_token_cache["token"]

    # 3 — fetch fresh
    try:
        resp = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        ttl = int(data.get("expires_in", 3600)) - 60   # 1-min safety buffer

        cache.set_cc_token(token, ttl)

        # Always keep in-process copy so we survive a Redis restart mid-session
        _cc_token_cache["token"] = token
        _cc_token_cache["exp"] = time.time() + ttl

        logger.info("Spotify CC token refreshed (ttl=%ds).", ttl)
        return token

    except Exception as exc:
        logger.warning("Could not fetch Spotify CC token: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Spotify /v1/tracks metadata enrichment (24-hour per-track cache)
# ---------------------------------------------------------------------------

def _fetch_spotify_track(spotify_id: str, token: str) -> Optional[dict]:
    """
    Return cached or freshly-fetched metadata for a single Spotify track ID.
    Cached for TTL_SPOTIFY_TRACK (24 h) in Redis.
    Returns None on rate-limit or any error.
    """
    # Cache hit
    cached = cache.get_spotify_track(spotify_id)
    if cached:
        return cached

    # Cache miss — go to Spotify
    try:
        resp = requests.get(
            f"https://api.spotify.com/v1/tracks/{spotify_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "unknown")
            logger.warning(
                "Spotify rate-limited on /v1/tracks/%s (Retry-After: %s).",
                spotify_id,
                retry_after,
            )
            return None
        if resp.status_code == 404:
            logger.debug("Spotify track %s not found.", spotify_id)
            return None
        resp.raise_for_status()

        track = resp.json()
        images = track.get("album", {}).get("images", [])
        meta = {
            "name": track.get("name"),
            "artist": (track.get("artists") or [{}])[0].get("name"),
            "album_art_url": images[0]["url"] if images else None,
        }
        cache.set_spotify_track(spotify_id, meta)
        return meta

    except Exception as exc:
        logger.warning("Spotify /v1/tracks/%s error: %s", spotify_id, exc)
        return None


def _enrich_from_spotify(spotify_ids: list[str], token: str) -> dict[str, dict]:
    """
    Enrich a list of Spotify IDs with metadata.

    Strategy: check each ID in the Redis cache first (O(N) pipeline pings but
    no network round-trip to Spotify).  Batch-fetch uncached IDs using the
    /v1/tracks?ids= bulk endpoint (up to 50 per call) and write each result
    back to cache individually.

    Returns a dict keyed by Spotify ID.
    """
    enriched: dict[str, dict] = {}
    uncached: list[str] = []

    # --- Check per-track cache ---
    for sid in spotify_ids:
        cached = cache.get_spotify_track(sid)
        if cached:
            enriched[sid] = cached
        else:
            uncached.append(sid)

    if not uncached or not token:
        return enriched

    # --- Batch-fetch uncached from Spotify ---
    headers = {"Authorization": f"Bearer {token}"}
    chunk_size = 50

    for i in range(0, len(uncached), chunk_size):
        chunk = uncached[i : i + chunk_size]
        try:
            resp = requests.get(
                "https://api.spotify.com/v1/tracks",
                params={"ids": ",".join(chunk)},
                headers=headers,
                timeout=5,
            )
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After", "unknown")
                logger.warning(
                    "Spotify rate-limited on batch /v1/tracks (Retry-After: %s)."
                    " Remaining %d IDs will use DB fallback.",
                    retry_after,
                    len(spotify_ids) - len(enriched),
                )
                break   # leave remaining tracks to DB fallback
            resp.raise_for_status()

            for track in resp.json().get("tracks") or []:
                if not track:
                    continue
                images = track.get("album", {}).get("images", [])
                meta = {
                    "name": track.get("name"),
                    "artist": (track.get("artists") or [{}])[0].get("name"),
                    "album_art_url": images[0]["url"] if images else None,
                }
                enriched[track["id"]] = meta
                # Cache each individual track for 24 h
                cache.set_spotify_track(track["id"], meta)

        except Exception as exc:
            logger.warning("Spotify batch /v1/tracks error: %s", exc)

    return enriched


# ---------------------------------------------------------------------------
# Corpus — load Track rows from PostgreSQL
# ---------------------------------------------------------------------------

def _build_corpus() -> tuple[list, np.ndarray]:
    """
    Load all Track rows and return (track_objects, feature_matrix).
    feature_matrix has shape (N, 6).
    """
    from api.models import Track   # local import avoids circular dependency

    tracks = Track.query.all()
    if not tracks:
        return [], np.empty((0, 6))

    matrix = np.array([t.feature_vector() for t in tracks], dtype=np.float32)
    return tracks, matrix


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_recommendations(
    seed_vector: list[float],
    n: int = 10,
    exclude_spotify_ids: Optional[list[str]] = None,
) -> tuple[list[dict], bool]:
    """
    Return ``(results, cache_hit)`` where:

    * ``results``   – top-*n* dicts: spotify_id, name, artist, genre,
                      album_art_url, similarity_pct
    * ``cache_hit`` – True when the full result set was served from Redis

    Parameters
    ----------
    seed_vector : list[float]
        6-D normalised feature vector:
        [tempo/250, energy, danceability, valence, acousticness, instrumentalness]
    n : int
        Number of recommendations to return (default 10).
    exclude_spotify_ids : list[str] | None
        Track IDs to exclude from results.
    """
    exclude = set(exclude_spotify_ids or [])

    # ── Cache key: SHA-256 of the vector + n (stable across runs) ──────────
    vec_str = json.dumps(seed_vector, separators=(",", ":"))  # compact, deterministic
    vec_hash = hashlib.sha256(vec_str.encode()).hexdigest()[:16]

    # ── 1. Try Redis (1-hour TTL) or in-process fallback ─────────────────────
    cached = cache.get_recommendations(vec_hash, n)
    if cached is not None:
        logger.debug("Recommendations cache HIT (key=%s:%d).", vec_hash, n)
        return cached, True

    fb_entry = _recs_fallback_cache.get((vec_hash, n))
    if fb_entry and fb_entry.get("exp", 0) > time.time():
        logger.debug("Recommendations in-process cache HIT (key=%s:%d).", vec_hash, n)
        return fb_entry["results"], True

    logger.debug("Recommendations cache MISS — computing (key=%s:%d).", vec_hash, n)

    # ── 2. Build corpus ─────────────────────────────────────────────────────
    tracks, matrix = _build_corpus()
    if not tracks:
        logger.warning("Track corpus is empty — run seed.py first.")
        return [], False

    # ── 3. Cosine similarity ─────────────────────────────────────────────────
    seed = np.array(seed_vector, dtype=np.float32).reshape(1, -1)
    sims = sk_cosine_sim(seed, matrix)[0]   # shape (N,)

    ranked = sorted(
        (
            (tracks[i], float(sims[i]))
            for i in range(len(tracks))
            if tracks[i].spotify_id not in exclude
        ),
        key=lambda x: x[1],
        reverse=True,
    )[:n]

    # ── 4. Spotify enrichment (per-track 24-h cache, graceful fallback) ─────
    token = _get_cc_token()
    spotify_meta: dict[str, dict] = {}
    if token:
        ids = [t.spotify_id for t, _ in ranked]
        spotify_meta = _enrich_from_spotify(ids, token)

    # ── 5. Assemble results ──────────────────────────────────────────────────
    results: list[dict] = []
    for track, sim in ranked:
        meta = spotify_meta.get(track.spotify_id, {})
        results.append({
            "spotify_id": track.spotify_id,
            "name": meta.get("name") or track.name,
            "artist": meta.get("artist") or track.artist,
            "genre": track.genre,
            "album_art_url": meta.get("album_art_url") or track.album_art_url,
            "similarity_pct": round(sim * 100, 1),
        })

    # ── 6. Write to Redis (1-hour TTL) and in-process fallback ──────────────
    cache.set_recommendations(vec_hash, n, results)
    _recs_fallback_cache[(vec_hash, n)] = {
        "results": results,
        "exp": time.time() + 3600,
    }

    return results, False


def vector_from_top_tracks(top_tracks_payload: dict) -> list[float]:
    """
    Derive a 6-D seed preference vector from a Spotify top-tracks payload.

    Strategy (in order):
    1. If any of the user's top tracks are in our PostgreSQL corpus, average
       their feature vectors.
    2. Otherwise use Spotify popularity as an energy proxy and fill defaults.
    """
    from api.models import Track   # local import

    if not top_tracks_payload or not top_tracks_payload.get("items"):
        return [0.5, 0.5, 0.5, 0.5, 0.2, 0.1]

    spotify_ids = [
        item["id"] for item in top_tracks_payload["items"] if "id" in item
    ]
    db_tracks = Track.query.filter(Track.spotify_id.in_(spotify_ids)).all()

    if db_tracks:
        vectors = np.array([t.feature_vector() for t in db_tracks], dtype=np.float32)
        return vectors.mean(axis=0).tolist()

    # Fallback: map popularity → rough energy proxy
    popularities = [
        item.get("popularity", 50) / 100.0
        for item in top_tracks_payload["items"]
        if "popularity" in item
    ]
    energy_proxy = float(np.mean(popularities)) if popularities else 0.5
    return [
        round(energy_proxy * 0.90, 3),
        round(energy_proxy, 3),
        round(energy_proxy * 0.85, 3),
        0.5,
        0.2,
        0.05,
    ]
