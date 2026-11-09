"""
recommender.py — Hybrid Music Recommendation Engine
=====================================================
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

Feature vector dimensions (all in [0, 1])
------------------------------------------
  [0] tempo / 250        (raw BPM normalised)
  [1] energy
  [2] danceability
  [3] valence
  [4] acousticness
  [5] instrumentalness

Redis cache
-----------
Spotify Client-Credentials tokens are cached in Redis (key: ``cc_token``)
for the token's declared ``expires_in`` TTL so we don't re-fetch on every
recommendation request.  Recommendation results are also cached per seed
vector for 5 minutes.

Usage
-----
    from api.recommender import get_recommendations

    recs = get_recommendations(
        seed_vector=[0.5, 0.8, 0.7, 0.6, 0.1, 0.0],
        n=10,
    )
    # → list of dicts with keys: spotify_id, name, artist, genre,
    #   album_art_url, similarity_pct
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
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis client (optional — degrades gracefully if Redis is unavailable)
# ---------------------------------------------------------------------------
_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    try:
        import redis
        _redis_client = redis.from_url(redis_url, decode_responses=True)
        _redis_client.ping()
        logger.info("Redis connected.")
        return _redis_client
    except Exception as exc:
        logger.warning("Redis unavailable — caching disabled. %s", exc)
        return None


# ---------------------------------------------------------------------------
# Spotify Client-Credentials token (no user login needed for /v1/tracks)
# ---------------------------------------------------------------------------

_cc_token_cache: dict = {}   # in-process fallback if Redis is absent


def _get_cc_token() -> Optional[str]:
    """
    Return a valid Spotify Client-Credentials access token, refreshing when
    expired.  Tries Redis first, then falls back to an in-process dict.
    """
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    r = _get_redis()
    cache_key = "cadenza:cc_token"

    # --- try cache ---
    if r:
        cached = r.get(cache_key)
        if cached:
            return cached
    elif _cc_token_cache.get("token") and _cc_token_cache.get("exp", 0) > time.time():
        return _cc_token_cache["token"]

    # --- fetch fresh ---
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

        if r:
            r.set(cache_key, token, ex=ttl)
        else:
            _cc_token_cache["token"] = token
            _cc_token_cache["exp"] = time.time() + ttl

        return token
    except Exception as exc:
        logger.warning("Could not fetch Spotify CC token: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Spotify metadata enrichment
# ---------------------------------------------------------------------------

def _enrich_from_spotify(spotify_ids: list[str], token: str) -> dict[str, dict]:
    """
    Call /v1/tracks?ids=... for up to 50 IDs at a time.
    Returns a dict keyed by Spotify track ID with keys: name, artist, album_art_url.
    """
    enriched: dict[str, dict] = {}
    chunk_size = 50
    headers = {"Authorization": f"Bearer {token}"}

    for i in range(0, len(spotify_ids), chunk_size):
        chunk = spotify_ids[i : i + chunk_size]
        try:
            resp = requests.get(
                "https://api.spotify.com/v1/tracks",
                params={"ids": ",".join(chunk)},
                headers=headers,
                timeout=5,
            )
            if resp.status_code == 429:
                logger.warning("Spotify rate-limited — using DB fallback for this chunk.")
                continue
            resp.raise_for_status()
            for track in resp.json().get("tracks") or []:
                if not track:
                    continue
                images = track.get("album", {}).get("images", [])
                enriched[track["id"]] = {
                    "name": track.get("name"),
                    "artist": track.get("artists", [{}])[0].get("name"),
                    "album_art_url": images[0]["url"] if images else None,
                }
        except Exception as exc:
            logger.warning("Spotify /v1/tracks error: %s", exc)

    return enriched


# ---------------------------------------------------------------------------
# Core recommendation logic
# ---------------------------------------------------------------------------

def _build_corpus() -> tuple[list, np.ndarray]:
    """
    Load all Track rows from PostgreSQL and return
    (track_objects, feature_matrix) where feature_matrix is shape (N, 6).
    """
    # Import here to avoid circular import at module load time
    from api.models import Track

    tracks = Track.query.all()
    if not tracks:
        return [], np.empty((0, 6))

    matrix = np.array([t.feature_vector() for t in tracks], dtype=np.float32)
    return tracks, matrix


def get_recommendations(
    seed_vector: list[float],
    n: int = 10,
    exclude_spotify_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    Return the top-*n* tracks closest to *seed_vector* by cosine similarity.

    Parameters
    ----------
    seed_vector : list[float]
        6-D normalised feature vector:
        [tempo/250, energy, danceability, valence, acousticness, instrumentalness]
    n : int
        Number of recommendations to return.
    exclude_spotify_ids : list[str] | None
        Spotify IDs to exclude (e.g. the seed track itself).

    Returns
    -------
    list[dict] — each dict has:
        spotify_id, name, artist, genre, album_art_url, similarity_pct
    """
    exclude = set(exclude_spotify_ids or [])

    # --- Redis cache (5-minute TTL per unique seed vector) ---
    r = _get_redis()
    cache_key = None
    if r:
        vec_hash = hashlib.md5(json.dumps(seed_vector, sort_keys=True).encode()).hexdigest()
        cache_key = f"cadenza:recs:{vec_hash}:{n}"
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)

    # --- build corpus ---
    tracks, matrix = _build_corpus()
    if not tracks:
        logger.warning("Track corpus is empty — run seed.py first.")
        return []

    # --- cosine similarity ---
    seed = np.array(seed_vector, dtype=np.float32).reshape(1, -1)
    sims = cosine_similarity(seed, matrix)[0]   # shape (N,)

    # Sort descending, skip excluded IDs
    ranked = sorted(
        ((tracks[i], float(sims[i])) for i in range(len(tracks)) if tracks[i].spotify_id not in exclude),
        key=lambda x: x[1],
        reverse=True,
    )[:n]

    # --- Spotify enrichment (graceful fallback) ---
    token = _get_cc_token()
    spotify_meta: dict[str, dict] = {}
    if token:
        ids = [t.spotify_id for t, _ in ranked]
        spotify_meta = _enrich_from_spotify(ids, token)

    # --- assemble result ---
    results = []
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

    # --- cache result ---
    if r and cache_key:
        r.set(cache_key, json.dumps(results), ex=300)   # 5-minute TTL

    return results


def vector_from_top_tracks(top_tracks_payload: dict) -> list[float]:
    """
    Derive a seed preference vector from a user's Spotify top-tracks payload.

    Because /v1/audio-features is deprecated, we map each track's popularity
    into a rough energy proxy and derive the other dimensions from genre/name
    heuristics stored in our DB.

    If the user's top tracks appear in our Track corpus, we average their
    feature vectors — otherwise we return a neutral default vector.
    """
    from api.models import Track

    if not top_tracks_payload or not top_tracks_payload.get("items"):
        return [0.5, 0.5, 0.5, 0.5, 0.2, 0.1]   # neutral default

    spotify_ids = [item["id"] for item in top_tracks_payload["items"] if "id" in item]
    db_tracks = Track.query.filter(Track.spotify_id.in_(spotify_ids)).all()

    if db_tracks:
        vectors = np.array([t.feature_vector() for t in db_tracks])
        avg = vectors.mean(axis=0).tolist()
        return avg

    # Fallback: use Spotify popularity to proxy energy
    popularities = [
        item.get("popularity", 50) / 100.0
        for item in top_tracks_payload["items"]
        if "popularity" in item
    ]
    energy_proxy = float(np.mean(popularities)) if popularities else 0.5
    return [energy_proxy * 0.9, energy_proxy, energy_proxy * 0.85, 0.5, 0.2, 0.05]
