#!/usr/bin/env bash
# =============================================================================
# entrypoint.sh — Cadenza web container startup script
# =============================================================================
#
# Responsibilities (in order):
#   1. Wait for PostgreSQL to accept connections  (up to 60 s)
#   2. Wait for Redis to respond to PING          (up to 30 s)
#   3. Create / migrate database tables via SQLAlchemy db.create_all()
#   4. Seed the tracks table if it is empty       (runs seed.py)
#   5. Start Gunicorn with eventlet worker class
#
# Environment variables consumed
# --------------------------------
#   DATABASE_URL          PostgreSQL DSN  (required)
#   REDIS_URL             Redis DSN       (optional — skipped if unset)
#   PORT                  Gunicorn bind port     (default 5000)
#   GUNICORN_WORKERS      Worker processes       (default 2)
#   GUNICORN_THREADS      Threads per worker     (default 2)
#   GUNICORN_TIMEOUT      Worker timeout seconds (default 120)
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[entrypoint]${NC} $*"; }
warn() { echo -e "${YELLOW}[entrypoint]${NC} $*"; }
err()  { echo -e "${RED}[entrypoint]${NC} $*" >&2; }

# ── 1. Wait for PostgreSQL ────────────────────────────────────────────────────
wait_for_postgres() {
    local max_attempts=60
    local attempt=0

    log "Waiting for PostgreSQL to be ready…"

    # Parse host and port from DATABASE_URL
    # Format: postgresql://user:pass@host:port/dbname
    local db_url="${DATABASE_URL:-}"
    if [[ -z "$db_url" ]]; then
        err "DATABASE_URL is not set. Aborting."
        exit 1
    fi

    local host port
    # Extract host:port using bash parameter expansion
    local hostport
    hostport=$(echo "$db_url" | sed -E 's|.*@([^/]+)/.*|\1|')
    host=$(echo "$hostport" | cut -d: -f1)
    port=$(echo "$hostport" | cut -d: -f2)
    port=${port:-5432}

    until python -c "
import socket, sys
try:
    s = socket.create_connection(('${host}', ${port}), timeout=2)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
        attempt=$((attempt + 1))
        if [[ $attempt -ge $max_attempts ]]; then
            err "PostgreSQL not reachable at ${host}:${port} after ${max_attempts}s. Aborting."
            exit 1
        fi
        warn "  PostgreSQL not ready (attempt ${attempt}/${max_attempts}) — retrying in 1s…"
        sleep 1
    done

    log "PostgreSQL is ready at ${host}:${port} ✓"
}

# ── 2. Wait for Redis (optional) ─────────────────────────────────────────────
wait_for_redis() {
    local redis_url="${REDIS_URL:-}"
    if [[ -z "$redis_url" ]]; then
        warn "REDIS_URL not set — skipping Redis health check (caching disabled)."
        return 0
    fi

    local max_attempts=30
    local attempt=0

    log "Waiting for Redis to be ready…"

    # Extract host:port from redis://host:port/db
    local hostport
    hostport=$(echo "$redis_url" | sed -E 's|redis://([^/]+).*|\1|')
    local host port
    host=$(echo "$hostport" | cut -d: -f1)
    port=$(echo "$hostport" | cut -d: -f2)
    port=${port:-6379}

    until python -c "
import socket, sys
try:
    s = socket.create_connection(('${host}', ${port}), timeout=2)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
        attempt=$((attempt + 1))
        if [[ $attempt -ge $max_attempts ]]; then
            warn "Redis not reachable at ${host}:${port} after ${max_attempts}s — continuing without cache."
            return 0  # Non-fatal — Redis is optional
        fi
        warn "  Redis not ready (attempt ${attempt}/${max_attempts}) — retrying in 1s…"
        sleep 1
    done

    log "Redis is ready at ${host}:${port} ✓"
}

# ── 3 & 4. Bootstrap database and seed ───────────────────────────────────────
bootstrap_db() {
    log "Running database bootstrap (create_all + conditional seed)…"

    python - <<'PYEOF'
import os, sys

# Ensure the app module is importable from /app
sys.path.insert(0, "/app")

from api.app import app
from api.models import db, Track

with app.app_context():
    # 3. Create all tables (idempotent — safe on every startup)
    db.create_all()
    print("[bootstrap] Tables created / verified ✓")

    # 4. Seed only if the tracks table is empty
    track_count = Track.query.count()
    if track_count == 0:
        print(f"[bootstrap] Track table is empty — running seed.py…")
        # Import and run the seeder directly (avoids a subprocess call)
        from seed import seed_from_list, SEED_TRACKS
        seed_from_list(SEED_TRACKS)
        print(f"[bootstrap] Seed complete: {Track.query.count()} tracks loaded ✓")
    else:
        print(f"[bootstrap] Track table already has {track_count} rows — skipping seed ✓")
PYEOF

    log "Database bootstrap complete ✓"
}

# ── 5. Start Gunicorn ─────────────────────────────────────────────────────────
start_gunicorn() {
    local port="${PORT:-5000}"
    local workers="${GUNICORN_WORKERS:-2}"
    local threads="${GUNICORN_THREADS:-2}"
    local timeout="${GUNICORN_TIMEOUT:-120}"

    log "Starting Gunicorn on 0.0.0.0:${port} (workers=${workers}, threads=${threads}, timeout=${timeout}s)…"

    exec gunicorn \
        --worker-class eventlet \
        --workers "${workers}" \
        --threads "${threads}" \
        --timeout "${timeout}" \
        --bind "0.0.0.0:${port}" \
        --access-logfile - \
        --error-logfile - \
        --log-level info \
        --forwarded-allow-ips="*" \
        "api.app:app"
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    log "=== Cadenza container starting ==="
    wait_for_postgres
    wait_for_redis
    bootstrap_db
    start_gunicorn
}

main "$@"
