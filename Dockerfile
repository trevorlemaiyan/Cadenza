# =============================================================================
# Cadenza — multi-stage production Dockerfile
# =============================================================================
#
# Stages
# ------
# builder  Install Python wheels into a virtual-env inside /venv so only the
#          venv (not pip caches, build tools, or headers) is copied to the
#          final image.  This keeps the final image lean (~200 MB vs ~700 MB).
#
# runtime  Copy /venv + application code onto python:3.11-slim.  No build
#          tools present — greatly reduces attack surface.
#
# Usage
# -----
#   docker build -t cadenza .
#   docker run -p 5000:5000 --env-file .env cadenza
#
# Or via Compose:
#   docker compose up --build
# =============================================================================

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# System packages needed to compile C extensions (psycopg2-binary ships
# pre-compiled wheels, but we keep gcc/libpq-dev here as a safety net for
# any platform where the wheel is unavailable).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated virtual environment so the runtime stage can COPY just /venv.
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Upgrade pip + wheel before installing dependencies.
RUN pip install --upgrade pip wheel

# Copy requirements first so Docker caches this layer independently of source changes.
COPY requirements.txt .

# Install all dependencies into /venv.
# --no-cache-dir keeps the layer small.
RUN pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="Cadenza"
LABEL org.opencontainers.image.description="Hybrid Music Recommendation Engine"
LABEL org.opencontainers.image.source="https://github.com/trevorlemaiyan/Cadenza"

# Runtime-only system libraries (libpq for psycopg2, bash for entrypoint).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        bash \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built virtual environment from the builder stage.
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# Non-root user — principle of least privilege.
RUN useradd --create-home --shell /bin/bash cadenza
WORKDIR /app

# Copy application source (each layer is separate so code changes don't
# invalidate the venv layer).
COPY --chown=cadenza:cadenza api/        ./api/
COPY --chown=cadenza:cadenza templates/  ./templates/
COPY --chown=cadenza:cadenza static/     ./static/
COPY --chown=cadenza:cadenza seed.py     ./seed.py
COPY --chown=cadenza:cadenza entrypoint.sh ./entrypoint.sh

# Make the entrypoint executable.
RUN chmod +x ./entrypoint.sh

USER cadenza

# Flask / Gunicorn configuration via environment variables.
# These are sane defaults; override in docker-compose.yml or .env.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=5000 \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=2 \
    GUNICORN_TIMEOUT=120

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
