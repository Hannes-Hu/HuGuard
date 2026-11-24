# ──────────────────────────────────────────────────────────────────────────────
# HuGuard AI – Backend Dockerfile
# Multi-stage build: builder → runtime
# Base: python:3.11-slim (Debian Bookworm)
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Dependency Builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Security: Don't run as root in builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install system dependencies for tree-sitter and bandit
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (layer cache optimization)
COPY requirements.txt .

# Install into a virtual environment for clean separation
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt

# ── Stage 2: Runtime Image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

WORKDIR /app

# Install only runtime system deps (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    # Create non-root user for security
    && groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source and tests
COPY app/ ./app/
COPY tests/ ./tests/
COPY pyproject.toml ./

# Create data and cache directories with correct permissions for non-root user
RUN mkdir -p /app/data /app/uploads /app/.pytest_cache && \
    touch /app/.coverage && \
    chown -R appuser:appgroup /app/data /app/uploads /app/.pytest_cache /app/tests /app/.coverage

# Switch to non-root user
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
