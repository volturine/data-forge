# Multi-stage Dockerfile for Data-Forge Analysis Platform
# Builds fixed-role release images from one codebase.

FROM oven/bun:1.2.22 AS frontend-builder
WORKDIR /app/packages/frontend
COPY packages/frontend/package.json packages/frontend/bun.lock* ./
RUN bun install --frozen-lockfile
COPY packages/frontend/ ./
RUN bun run panda:codegen && bun run build

FROM python:3.13.7-slim AS backend-base
WORKDIR /app/packages/shared

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

COPY packages/shared/ ./
COPY packages/backend/ /app/packages/backend/
COPY packages/scheduler/ /app/packages/scheduler/
COPY packages/worker-manager/ /app/packages/worker-manager/
COPY Justfile /app/Justfile
COPY scripts/ /app/scripts/

RUN if [ "$INSTALL_DEV" = "true" ]; then uv sync --frozen --group dev; else uv sync --frozen; fi

COPY --from=frontend-builder /app/packages/frontend/build /app/packages/frontend/build

RUN mkdir -p /app/data/default/uploads /app/data/default/clean /app/data/default/exports /app/packages/shared/database && \
    chmod -R 755 /app/data /app/packages/shared/database

RUN chown -R appuser:appgroup /app

USER appuser
WORKDIR /app/packages/shared
ENV PATH="/app/packages/shared/.venv/bin:${PATH}"
EXPOSE 8000

FROM backend-base AS runtime-base
RUN chown -R appuser:appgroup /app/data /app/packages/shared/database

FROM runtime-base AS api
ENV PYTHONPATH="/app/packages/backend:/app/packages/shared"
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready').status==200 else 1)"
CMD ["python3", "../backend/main.py"]

FROM runtime-base AS scheduler
ENV PYTHONPATH="/app/packages/scheduler:/app/packages/shared"
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import sys; from core.docker_healthcheck import worker_healthy; from contracts.runtime_workers.models import RuntimeWorkerKind; sys.exit(0 if worker_healthy(kind=RuntimeWorkerKind.SCHEDULER) else 1)"
CMD ["python3", "../scheduler/main.py"]

FROM runtime-base AS worker
ENV PYTHONPATH="/app/packages/worker-manager:/app/packages/shared"
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import sys; from core.docker_healthcheck import worker_healthy; from contracts.runtime_workers.models import RuntimeWorkerKind; sys.exit(0 if worker_healthy(kind=RuntimeWorkerKind.BUILD_MANAGER) else 1)"
CMD ["python3", "../worker-manager/main.py"]
