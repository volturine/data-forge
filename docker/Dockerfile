# Multi-stage Dockerfile for Data-Forge Analysis Platform
# Builds fixed-role release images from one codebase.

ARG BUN_VERSION=1.3.11
ARG PYTHON_VERSION=3.14.6
ARG UV_VERSION=0.9.5
FROM oven/bun:${BUN_VERSION} AS bun-runtime
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-runtime

FROM python:${PYTHON_VERSION}-slim-trixie AS protocol-builder
WORKDIR /app
COPY --from=bun-runtime /usr/local/bin/bun /usr/local/bin/bun
COPY --from=uv-runtime /uv /usr/local/bin/uv
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates just && \
    ln -s /usr/local/bin/bun /usr/local/bin/node && \
    rm -rf /var/lib/apt/lists/*
COPY Justfile /app/Justfile
COPY packages/protocol/ /app/packages/protocol/
COPY packages/backend/ /app/packages/backend/
COPY packages/scheduler/ /app/packages/scheduler/
COPY packages/worker/ /app/packages/worker/
RUN mkdir -p /app/packages/frontend/src/lib
RUN just generate-protocol

FROM python:${PYTHON_VERSION}-slim-trixie AS python-builder
COPY --from=uv-runtime /uv /usr/local/bin/uv
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

FROM python-builder AS engine-builder
COPY packages/worker/ /app/packages/worker/
COPY --from=protocol-builder /app/packages/worker/buf /app/packages/worker/buf
COPY --from=protocol-builder /app/packages/worker/dataforge_protocol /app/packages/worker/dataforge_protocol
WORKDIR /app/packages/worker
RUN uv sync --frozen --no-dev

FROM python:${PYTHON_VERSION}-slim-trixie AS engine
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG APP_VERSION=unknown
LABEL org.opencontainers.image.title="Data-Forge Polars Engine"
LABEL org.opencontainers.image.description="Isolated Polars compute engine"
LABEL org.opencontainers.image.version="${APP_VERSION}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
RUN addgroup --gid 1000 appgroup && \
    adduser --uid 1000 --gid 1000 --disabled-password --gecos "" appuser
COPY --from=engine-builder --chown=appuser:appgroup /app/packages/worker /app/packages/worker
WORKDIR /app/packages/worker
USER appuser
ENV PATH="/app/packages/worker/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/packages/worker"
HEALTHCHECK NONE
CMD ["python3", "engine_main.py"]

FROM oven/bun:${BUN_VERSION}-alpine AS frontend-builder
WORKDIR /app/packages/frontend
COPY packages/frontend/package.json packages/frontend/bun.lock* ./
RUN bun install --frozen-lockfile
COPY packages/frontend/ ./
COPY --from=protocol-builder /app/packages/frontend/src/lib/protocol /app/packages/frontend/src/lib/protocol
RUN bun run panda:codegen && bun run build

FROM python:${PYTHON_VERSION}-slim-trixie AS app-runtime
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG APP_VERSION=unknown
LABEL org.opencontainers.image.title="Data-Forge"
LABEL org.opencontainers.image.description="Postgres-backed Data-Forge runtime image"
LABEL org.opencontainers.image.version="${APP_VERSION}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.source="https://github.com/volturine/data-forge"
LABEL org.opencontainers.image.licenses="MIT"
RUN addgroup --gid 1000 appgroup && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" appuser

FROM python-builder AS api-builder
ARG INSTALL_DEV=false
COPY packages/backend/ /app/packages/backend/
COPY --from=protocol-builder /app/packages/backend/buf /app/packages/backend/buf
COPY --from=protocol-builder /app/packages/backend/dataforge_protocol /app/packages/backend/dataforge_protocol
WORKDIR /app/packages/backend
RUN if [ "$INSTALL_DEV" = "true" ]; then uv sync --frozen --group dev; else uv sync --frozen --no-dev; fi

FROM app-runtime AS api
COPY --from=api-builder --chown=appuser:appgroup /app/packages/backend /app/packages/backend
COPY --from=frontend-builder --chown=appuser:appgroup /app/packages/frontend/build /app/packages/frontend/build
RUN mkdir -p /app/data/default/uploads /app/data/default/clean /app/data/default/exports /app/packages/backend/database && \
    chmod -R 755 /app/data /app/packages/backend/database && \
    chown -R appuser:appgroup /app/data /app/packages/backend/database
USER appuser
WORKDIR /app/packages/backend
ENV PATH="/app/packages/backend/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/packages/backend"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready').status==200 else 1)"
CMD ["python3", "main.py"]

FROM python-builder AS scheduler-builder
COPY packages/scheduler/ /app/packages/scheduler/
COPY --from=protocol-builder /app/packages/scheduler/buf /app/packages/scheduler/buf
COPY --from=protocol-builder /app/packages/scheduler/dataforge_protocol /app/packages/scheduler/dataforge_protocol
WORKDIR /app/packages/scheduler
RUN uv sync --frozen --no-dev

FROM app-runtime AS scheduler
COPY --from=scheduler-builder --chown=appuser:appgroup /app/packages/scheduler /app/packages/scheduler
USER appuser
WORKDIR /app/packages/scheduler
ENV PATH="/app/packages/scheduler/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/packages/scheduler"
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD python3 -c "import os,psycopg; c=psycopg.connect(os.environ['DATABASE_URL'].replace('+psycopg','')); r=c.execute(\"select count(*) from public.runtime_workers where kind='scheduler' and stopped_at is null\").fetchone(); c.close(); exit(0 if (r or [0])[0] > 0 else 1)"
CMD ["python3", "main.py"]

FROM app-runtime AS worker
COPY --from=engine-builder --chown=appuser:appgroup /app/packages/worker /app/packages/worker
USER appuser
WORKDIR /app/packages/worker
ENV PATH="/app/packages/worker/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/packages/worker"
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD python3 -c "import os,psycopg; c=psycopg.connect(os.environ['DATABASE_URL'].replace('+psycopg','')); r=c.execute(\"select count(*) from public.runtime_workers where kind='build_manager' and stopped_at is null\").fetchone(); c.close(); exit(0 if (r or [0])[0] > 0 else 1)"
CMD ["python3", "main.py"]
