# Cadenza — Hybrid Music Recommendation Engine

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Flask 3](https://img.shields.io/badge/Flask-3.1-black.svg)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-red.svg)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Cadenza** is a production-ready **Hybrid Music Recommendation Engine and Social Platform** built with **Flask, PostgreSQL (SQLAlchemy), Redis, Scikit-Learn, and the Spotify Web API**.

Because Spotify deprecated the `/v1/audio-features` and `/v1/recommendations` endpoints for standard developer applications, Cadenza solves this with an in-house **6-dimensional vector recommendation engine**:
1. Storing curated, normalized acoustic feature vectors in **PostgreSQL**.
2. Computing high-performance **Cosine Similarity** via **Scikit-Learn / NumPy**.
3. Caching recommendation vectors (1-hour TTL) and Spotify metadata lookups (24-hour TTL) via a resilient **Redis** connection pool.
4. Serving real-time chat via **Flask-SocketIO** with persistent message history.

---

## Architecture Overview

```
                                      ┌─────────────────────────────────────┐
                                      │           Client Browser            │
                                      └──────────────────┬──────────────────┘
                                                         │
                                           HTTP / WebSocket (Port 5000)
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │        Flask / Gunicorn (Web)       │
                                      │        (api/app.py & wsgi.py)       │
                                      └───────┬──────────────┬──────────────┘
                                              │              │
                   SQLAlchemy Models          │              │  Redis Connection Pool
               (Track, User, Message)         │              │  (api/cache.py)
                                              ▼              ▼
                                     ┌────────────────┐ ┌────────────────┐
                                     │  PostgreSQL 16 │ │    Redis 7     │
                                     │  (db service)  │ │ (redis service)│
                                     └────────────────┘ └────────────────┘
                                              ▲
                                              │
                                     ┌────────┴────────┐
                                     │ Recommender     │ ◄─── Spotify API (/v1/tracks)
                                     │ Engine          │      (Client Credentials +
                                     │ (Cosine Sim)    │       graceful DB fallback)
                                     └─────────────────┘
```

---

## Features

- **Hybrid Recommendation Engine:** Computes cosine similarity across a 6-D vector space (`[tempo/250, energy, danceability, valence, acousticness, instrumentalness]`).
- **Resilient Redis Caching Layer (`api/cache.py`):**
  - Thread-safe Redis connection pool (`max_connections=20`, `socket_timeout=2s`).
  - Caches Spotify `/v1/tracks` metadata for **24 hours** (`cadenza:spotify:track:<id>`).
  - Caches recommendation lists for **1 hour** (`cadenza:recs:<sha256>:<n>`).
  - Adds `X-Cache: HIT|MISS` and `X-Response-Time-Ms` response headers for real-time benchmark verification.
  - Zero-exception graceful fallback if Redis is unavailable or unconfigured.
- **Automated Database Seeding:** Ships with 500+ curated tracks spanning 18 genres (Afro House, Amapiano, Afrobeats, Hip-Hop, R&B, Electronic, Rock, Pop, Jazz, Classical, etc.), seeded automatically on startup if the database is empty.
- **Spotify OAuth Integration:** Reads user top tracks and top artists to derive custom acoustic preference vectors.
- **Social Matching & Real-Time Chat:** Jaccard-similarity matching between users and room-isolated Socket.IO real-time chat with persistent message history in PostgreSQL.
- **Health Check Endpoint (`/health`):** Live JSON probes testing PostgreSQL query execution and Redis latency.
- **Containerized for One-Command Launch:** Multi-stage production `Dockerfile` (Python 3.11-slim) and `docker-compose.yml` with automated readiness healthchecks.

---

## Quick Start (Docker Compose)

Get the entire stack (Flask app, PostgreSQL 16, and Redis 7) running with a single command:

```bash
# 1. Clone repository
git clone https://github.com/trevorlemaiyan/Cadenza.git
cd Cadenza

# 2. (Optional) Copy env file and add Spotify developer keys
cp .env.example .env

# 3. Start containers with automatic build & database seeding
docker compose up --build
```

The app will be live at **http://localhost:5000**.
- The `entrypoint.sh` automatically waits for PostgreSQL & Redis healthchecks.
- It creates tables and runs `seed.py` on first launch if the database is empty.
- View system health at **http://localhost:5000/health**.

To stop and remove containers:
```bash
docker compose down
# Or to wipe database volumes as well:
docker compose down -v
```

---

## Local Development (Without Docker)

If you prefer to run natively on your machine:

```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install pinned dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env to set DATABASE_URL (defaults to SQLite if unset) and optional REDIS_URL

# 4. Populate database with curated tracks
python seed.py

# 5. Start development server
flask --app api.app run --port 5000
```

---

## Running Automated Tests

Cadenza includes automated test suites covering API health, recommendation vectors, and Redis fallback behavior using an in-memory SQLite fixture:

```bash
python -m pytest tests/ -v
```

---

## API Endpoints

| Method | Endpoint | Description | Query Parameters / Headers |
|---|---|---|---|
| `GET` | `/health` | Live PostgreSQL and Redis health diagnostics | Returns `{status, postgres, redis}` |
| `GET` | `/api/recommendations` | JSON recommendation engine | Query: `?tempo=&energy=&danceability=&valence=&n=`<br>Headers: `X-Cache: HIT\|MISS`, `X-Response-Time-Ms` |
| `GET` | `/recommendations` | Visual recommendation UI with feature vector bars | Interactive profile-derived recommendations |
| `GET` | `/matches` | Find matched listeners based on taste overlap | User card gallery with match percentage |
| `GET` | `/chat/<room_id>` | Real-time chat room between matched users | WebSocket with persisted database history |
| `GET` | `/login` | Spotify OAuth authorization redirect | Scopes: `user-top-read`, `user-read-private` |

---

## Project Structure

```
Cadenza/
├── api/
│   ├── app.py              # Main Flask application, routes, and Socket.IO handlers
│   ├── cache.py            # Redis caching layer with connection pooling & fallbacks
│   ├── models.py           # SQLAlchemy Track, User, and Message schema
│   ├── recommender.py      # Cosine-similarity engine & Spotify enrichment
│   └── wsgi.py             # WSGI entrypoint for Gunicorn
├── static/
│   ├── app.js              # Real-time WebSocket chat client
│   └── styles.css          # Dark Spotify-themed design system
├── templates/
│   ├── chat.html           # Real-time chat view with message history
│   ├── index.html          # Landing page
│   ├── matches.html        # Social match card grid
│   ├── profile.html        # User Spotify profile and top music
│   └── recommendations.html# Interactive recommendation explorer
├── tests/
│   ├── conftest.py         # Pytest in-memory test configuration
│   ├── test_cache.py       # Redis cache fallback unit tests
│   ├── test_health.py      # /health and /api/recommendations integration tests
│   └── test_recommender.py # Cosine similarity and vector computation tests
├── .dockerignore           # Excludes development artifacts from Docker context
├── .env.example            # Documented environment template with working defaults
├── .gitattributes          # Enforces LF line endings for scripts across OSs
├── docker-compose.yml      # Orchestration for web, postgres:16-alpine, redis:7-alpine
├── Dockerfile              # Multi-stage production container build (Python 3.11-slim)
├── entrypoint.sh           # Container startup: waits for DB/Redis, runs seed.py, launches Gunicorn
├── pytest.ini              # Pytest configuration
├── requirements.txt        # Pinned production and test dependencies
└── seed.py                 # Idempotent seeder: 500+ tracks across 18 genres
```

---

## License

This project is licensed under the MIT License.
