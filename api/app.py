"""
Cadenza — Hybrid Music Recommendation Engine
=============================================
Flask + PostgreSQL (SQLAlchemy) + Redis (api/cache.py) + Spotify API

Routes
------
GET  /                       Landing page
GET  /login                  Redirect to Spotify OAuth
GET  /callback               Exchange code → token; upsert user in PostgreSQL
GET  /profile                Show user's top tracks / artists
GET  /matches                Find users with similar taste (Jaccard similarity)
GET  /recommendations        Track recommendations page (HTML)
GET  /api/recommendations    JSON recommendation endpoint
         ?tempo=&energy=&danceability=&valence=&acousticness=&instrumentalness=&n=
         Response headers: X-Cache (HIT|MISS), X-Response-Time-Ms
GET  /health                 JSON health check for PostgreSQL + Redis
GET  /chat/<room_id>         Private room chat (with persisted history)

Socket.IO events: join | leave | message
"""

from __future__ import annotations

import os
import time
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, make_response, redirect, render_template, request, session, url_for, jsonify
from flask_socketio import SocketIO, join_room, leave_room, send
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

# ---------------------------------------------------------------------------
# App & extensions
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

# ── PostgreSQL (SQLAlchemy) ─────────────────────────────────────────────────
# Falls back to SQLite for local dev if DATABASE_URL is not set
_pg_url = os.getenv("DATABASE_URL", "sqlite:///cadenza.db")
# Heroku/Railway provide postgres:// but SQLAlchemy 1.4+ needs postgresql://
if _pg_url.startswith("postgres://"):
    _pg_url = _pg_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = _pg_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

from api.models import db, User, Track, Message  # noqa: E402

db.init_app(app)

# ── Redis cache (api/cache.py singleton) ────────────────────────────────────
from api.cache import cache as redis_cache  # noqa: E402

# ── Socket.IO ───────────────────────────────────────────────────────────────
socketio = SocketIO(app, async_mode="eventlet")

# ── Spotify credentials ──────────────────────────────────────────────────────
client_id = os.getenv("SPOTIFY_CLIENT_ID")
client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:5000/callback")

# ── MongoDB (legacy, optional dual-write) ───────────────────────────────────
_mongo_uri = os.getenv("MONGO_URI")
users_collection = None
if _mongo_uri:
    try:
        from pymongo import MongoClient
        _mongo_client = MongoClient(_mongo_uri)
        _mongo_db = _mongo_client["cadenza_db"]
        users_collection = _mongo_db["users"]
        users_collection.create_index("spotify_id", unique=True)
        print("[OK] Connected to MongoDB (legacy dual-write mode)")
    except Exception as exc:
        print(f"[WARN] MongoDB unavailable — PostgreSQL-only mode: {exc}")


# ---------------------------------------------------------------------------
# DB bootstrap (creates tables on first run)
# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_pg_user(spotify_id: str) -> User | None:
    return User.query.filter_by(spotify_id=spotify_id).first()


def _upsert_pg_user(
    me: dict, top_tracks: dict, top_artists: dict, access_token: str
) -> User:
    spotify_id = me["id"]
    user = User.query.filter_by(spotify_id=spotify_id).first()
    if not user:
        user = User(spotify_id=spotify_id)
        db.session.add(user)

    user.display_name = me.get("display_name") or spotify_id
    user.avatar_url = me["images"][0]["url"] if me.get("images") else None
    user.access_token = access_token
    user.top_tracks = top_tracks
    user.top_artists = top_artists
    db.session.commit()
    return user


def _calculate_similarity(user1: User, user2: User) -> float:
    """Jaccard similarity over shared top-artist IDs."""
    try:
        ids1 = {a["id"] for a in (user1.top_artists or {}).get("items", [])}
        ids2 = {a["id"] for a in (user2.top_artists or {}).get("items", [])}
        union = ids1 | ids2
        return len(ids1 & ids2) / len(union) if union else 0.0
    except (KeyError, TypeError):
        return 0.0


def _pg_health() -> dict:
    """Return PostgreSQL connectivity status dict."""
    try:
        t0 = time.perf_counter()
        db.session.execute(db.text("SELECT 1"))
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {"status": "connected", "latency_ms": latency_ms}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


# ---------------------------------------------------------------------------
# Routes — pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login")
def login():
    scope = "user-top-read user-read-private user-read-email"
    auth_url = "https://accounts.spotify.com/authorize?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "scope": scope,
        "redirect_uri": redirect_uri,
    })
    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("index"))

    try:
        token_resp = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
        session["access_token"] = access_token
    except Exception as exc:
        app.logger.error("Token exchange error: %s", exc)
        return "Error fetching access token", 500

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        me = requests.get("https://api.spotify.com/v1/me", headers=headers, timeout=10).json()
        top_tracks = requests.get(
            "https://api.spotify.com/v1/me/top/tracks", headers=headers, timeout=10
        ).json()
        top_artists = requests.get(
            "https://api.spotify.com/v1/me/top/artists", headers=headers, timeout=10
        ).json()

        spotify_id = me["id"]
        session["spotify_id"] = spotify_id
        session["display_name"] = me.get("display_name") or spotify_id

        _upsert_pg_user(me, top_tracks, top_artists, access_token)

        if users_collection is not None:
            users_collection.update_one(
                {"spotify_id": spotify_id},
                {"$set": {
                    "spotify_id": spotify_id,
                    "display_name": me.get("display_name") or spotify_id,
                    "avatar_url": me["images"][0]["url"] if me.get("images") else None,
                    "access_token": access_token,
                    "top_tracks": top_tracks,
                    "top_artists": top_artists,
                }},
                upsert=True,
            )
    except Exception as exc:
        app.logger.error("Spotify profile error: %s", exc)
        return "Error fetching user data from Spotify", 500

    return redirect(url_for("profile"))


@app.route("/profile")
def profile():
    spotify_id = session.get("spotify_id")
    if not spotify_id:
        return redirect(url_for("login"))

    user = _get_pg_user(spotify_id)
    if not user:
        return redirect(url_for("login"))

    return render_template(
        "profile.html",
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        top_tracks=user.top_tracks or {},
        top_artists=user.top_artists or {},
    )


@app.route("/matches")
def get_matches():
    spotify_id = session.get("spotify_id")
    if not spotify_id:
        return redirect(url_for("login"))

    try:
        user = _get_pg_user(spotify_id)
        other_users = User.query.filter(User.spotify_id != spotify_id).all()

        matches = []
        for other in other_users:
            sim = _calculate_similarity(user, other)
            room_id = "_".join(sorted([spotify_id, other.spotify_id]))
            top_artist = "Unknown"
            if other.top_artists and other.top_artists.get("items"):
                top_artist = other.top_artists["items"][0].get("name", "Unknown")
            matches.append({
                "display_name": other.display_name or other.spotify_id,
                "avatar_url": other.avatar_url,
                "similarity": round(sim * 100),
                "room_id": room_id,
                "top_artist": top_artist,
            })

        matches.sort(key=lambda x: x["similarity"], reverse=True)
    except Exception as exc:
        app.logger.error("Matches error: %s", exc)
        return "Error fetching matches", 500

    return render_template("matches.html", matches=matches)


@app.route("/recommendations")
def recommendations():
    """
    HTML recommendation page — derives preference vector from top tracks.
    """
    spotify_id = session.get("spotify_id")
    if not spotify_id:
        return redirect(url_for("login"))

    user = _get_pg_user(spotify_id)
    if not user:
        return redirect(url_for("login"))

    from api.recommender import get_recommendations, vector_from_top_tracks

    seed_vec = vector_from_top_tracks(user.top_tracks or {})
    recs, _ = get_recommendations(seed_vector=seed_vec, n=12)

    return render_template(
        "recommendations.html",
        recommendations=recs,
        seed_vector=seed_vec,
    )


# ---------------------------------------------------------------------------
# Routes — JSON API
# ---------------------------------------------------------------------------

@app.route("/api/recommend")
@app.route("/api/recommendations")
def api_recommendations():
    """
    JSON recommendation endpoint.

    Query parameters (all optional — authenticated users get profile-derived vector)
    ---------------------------------------------------------------------------------
    tempo            float [0–1]   raw BPM ÷ 250
    energy           float [0–1]
    danceability     float [0–1]
    valence          float [0–1]
    acousticness     float [0–1]
    instrumentalness float [0–1]
    n                int           number of results (default 10, max 50)

    Response headers
    ----------------
    X-Cache             HIT | MISS
    X-Response-Time-Ms  wall-clock time in milliseconds (float)
    """
    t_start = time.perf_counter()

    # ── Build seed vector ──────────────────────────────────────────────────
    spotify_id = session.get("spotify_id")
    try:
        vec = [
            float(request.args.get("tempo", 0.5)),
            float(request.args.get("energy", 0.5)),
            float(request.args.get("danceability", 0.5)),
            float(request.args.get("valence", 0.5)),
            float(request.args.get("acousticness", 0.2)),
            float(request.args.get("instrumentalness", 0.1)),
        ]
    except ValueError:
        return jsonify({"error": "Invalid vector parameter — must be numeric [0–1]."}), 400

    # Authenticated users get vector derived from their Spotify profile
    if spotify_id:
        user = _get_pg_user(spotify_id)
        if user:
            from api.recommender import vector_from_top_tracks
            vec = vector_from_top_tracks(user.top_tracks or {})

    # Clamp n to [1, 50]
    try:
        n = max(1, min(50, int(request.args.get("n", 10))))
    except ValueError:
        n = 10

    # ── Run recommendation engine ──────────────────────────────────────────
    from api.recommender import get_recommendations
    results, cache_hit = get_recommendations(seed_vector=vec, n=n)

    # ── Build response with diagnostic headers ─────────────────────────────
    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)

    resp = make_response(jsonify(results))
    resp.headers["X-Cache"] = "HIT" if cache_hit else "MISS"
    resp.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    resp.headers["Cache-Control"] = "no-store"   # don't let CDNs cache personalised results
    return resp


@app.route("/health")
def health():
    """
    Health check endpoint.

    Returns 200 when both PostgreSQL and Redis (if configured) are reachable,
    503 otherwise.

    Example response (all healthy):
        {
            "status": "healthy",
            "postgres": {"status": "connected", "latency_ms": 1.4},
            "redis":    {"status": "connected", "latency_ms": 0.9}
        }

    Example response (Redis not configured):
        {
            "status": "healthy",
            "postgres": {"status": "connected", "latency_ms": 1.4},
            "redis":    {"status": "not_configured"}
        }
    """
    pg_status = _pg_health()
    redis_status = redis_cache.health_check()

    # Overall health: unhealthy only if PostgreSQL (the critical service) is down
    overall = "healthy" if pg_status["status"] == "connected" else "unhealthy"
    http_status = 200 if overall == "healthy" else 503

    payload = {
        "status": overall,
        "postgres": pg_status,
        "redis": redis_status,
    }
    return jsonify(payload), http_status


@app.route("/chat/<room_id>")
def chat(room_id: str):
    spotify_id = session.get("spotify_id")
    if not spotify_id:
        return redirect(url_for("login"))

    user_ids = room_id.split("_")
    if spotify_id not in user_ids:
        return "Unauthorized", 403

    other_id = next((uid for uid in user_ids if uid != spotify_id), None)
    other_user = _get_pg_user(other_id) if other_id else None
    other_name = (other_user.display_name or other_id) if other_user else other_id

    history = (
        Message.query.filter_by(room_id=room_id)
        .order_by(Message.sent_at.asc())
        .limit(50)
        .all()
    )
    return render_template(
        "chat.html",
        room_id=room_id,
        other_name=other_name,
        history=history,
        my_spotify_id=spotify_id,
    )


# ---------------------------------------------------------------------------
# Socket.IO — private room-based chat with message persistence
# ---------------------------------------------------------------------------

@socketio.on("join")
def on_join(data):
    room = data.get("room")
    if room:
        join_room(room)
        send("Connected to chat.", to=room)


@socketio.on("leave")
def on_leave(data):
    room = data.get("room")
    if room:
        leave_room(room)


@socketio.on("message")
def handle_message(data):
    room = data.get("room")
    msg = data.get("msg", "").strip()
    sender = data.get("sender", "Someone")
    sender_id = data.get("sender_id", "")

    if room and msg:
        try:
            m = Message(
                room_id=room,
                sender_spotify_id=sender_id,
                sender_name=sender,
                body=msg,
            )
            db.session.add(m)
            db.session.commit()
        except Exception as exc:
            app.logger.warning("Could not persist message: %s", exc)
            db.session.rollback()

        send({"msg": msg, "sender": sender}, to=room)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run():
    socketio.run(app)


if __name__ == "__main__":
    socketio.run(app, debug=True)
