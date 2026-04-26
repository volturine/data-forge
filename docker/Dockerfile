# Multi-stage Dockerfile for Data-Forge Analysis Platform
# Builds fixed-role release images from one codebase

FROM oven/bun:1.2.22 AS frontend-builder

WORKDIR /app/frontend

# Copy package files
COPY frontend/package.json frontend/bun.lock* ./

# Install dependencies
RUN bun install --frozen-lockfile

# Copy frontend source
COPY frontend/ .

# Build static site
# The build will be output to /app/frontend/build
RUN bun run build

FROM python:3.13.7-slim AS backend-base

WORKDIR /app/backend

ARG UV_VERSION=0.9.5
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG APP_VERSION=unknown
ARG INSTALL_DEV=false

LABEL org.opencontainers.image.title="Data-Forge"
LABEL org.opencontainers.image.description="Postgres-backed Data-Forge runtime image"
LABEL org.opencontainers.image.version="${APP_VERSION}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.source="https://github.com/volturine/data-forge"
LABEL org.opencontainers.image.licenses="MIT"

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

RUN addgroup --gid 1000 appgroup && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" appuser

COPY backend/pyproject.toml backend/uv.lock* backend/README.md ./

RUN if [ "$INSTALL_DEV" = "true" ]; then uv sync --frozen --group dev || uv sync --group dev; else uv sync --frozen || uv sync; fi
RUN if [ "$INSTALL_DEV" = "true" ]; then uv sync --frozen --group dev; else uv sync --frozen; fi

COPY backend/ /app/backend/
COPY --from=frontend-builder /app/frontend/build /app/frontend/build

RUN mkdir -p /app/data/default/uploads /app/data/default/clean /app/data/default/exports /app/backend/database && \
    chmod -R 755 /app/data /app/backend/database

RUN chown -R appuser:appgroup /app

USER appuser
WORKDIR /app/backend
ENV PATH="/app/backend/.venv/bin:${PATH}"
EXPOSE 8000

FROM backend-base AS runtime-base

COPY --chown=appuser:appgroup backend/ /app/backend/
COPY --chown=appuser:appgroup --from=frontend-builder /app/frontend/build /app/frontend/build

RUN chown -R appuser:appgroup /app/data /app/backend/database

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

FROM runtime-base AS api
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"
CMD ["python", "main.py"]

FROM runtime-base AS scheduler
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys; from core.docker_healthcheck import worker_healthy; from modules.runtime_workers.models import RuntimeWorkerKind; sys.exit(0 if worker_healthy(kind=RuntimeWorkerKind.SCHEDULER) else 1)"
CMD ["python", "scheduler.py"]

FROM runtime-base AS worker
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys; from core.docker_healthcheck import worker_healthy; from modules.runtime_workers.models import RuntimeWorkerKind; sys.exit(0 if worker_healthy(kind=RuntimeWorkerKind.BUILD_MANAGER) else 1)"
CMD ["python", "worker.py"]
