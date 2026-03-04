# ─── Stage 1: Builder ────────────────────────────────────────────────────────
# Install Python dependencies with build tools; artifacts copied to runtime stage.
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build tools only needed here — not in final image
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install all Python packages into an isolated prefix so they can be copied cleanly
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install uv


# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
# Lean production image — no gcc, no build artifacts.
FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/install/lib/python3.11/site-packages

# Runtime-only system packages: curl (health check) + Node.js 20 (MCP npx servers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create non-root user and required directories
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/data /app/logs /tmp \
    && chown -R appuser:appuser /app \
    && chmod +x /app/scripts/entrypoint.sh

USER appuser

# Expose port
EXPOSE 8000

# Health check — curl avoids Python import errors masking real failures
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Run migrations then start the application
CMD ["/app/scripts/entrypoint.sh"]
