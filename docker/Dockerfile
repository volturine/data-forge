# Multi-stage Dockerfile for Data-Forge Analysis Platform
# Builds fixed-role release images from one codebase.

ARG BUN_VERSION=1.3.11
FROM oven/bun:${BUN_VERSION} AS frontend-builder
WORKDIR /app/packages/frontend
COPY packages/frontend/package.json packages/frontend/bun.lock* ./
RUN bun install --frozen-lockfile
COPY packages/frontend/ ./
RUN bun run panda:codegen && bun run build

FROM oven/bun:${BUN_VERSION} AS protocol-builder
WORKDIR /app
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*
COPY packages/protocol/ /app/packages/protocol/
COPY packages/backend/ /app/packages/backend/
COPY packages/scheduler/ /app/packages/scheduler/
COPY packages/worker/ /app/packages/worker/
RUN cd packages/protocol && bunx @bufbuild/buf@1.70.0 generate

FROM python:3.14.3-slim AS backend-base
WORKDIR /app/packages/backend

ARG UV_VERSION=0.9.5
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG APP_VERSION=unknown
ARG INSTALL_DEV=false
ENV DEBIAN_FRONTEND=noninteractive
LABEL org.opencontainers.image.title="Data-Forge"
LABEL org.opencontainers.image.description="Postgres-backed Data-Forge runtime image"
LABEL org.opencontainers.image.version="${APP_VERSION}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.source="https://github.com/volturine/data-forge"
LABEL org.opencontainers.image.licenses="MIT"

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

RUN addgroup --gid 1000 appgroup && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" appuser

COPY packages/backend/ /app/packages/backend/
COPY packages/scheduler/ /app/packages/scheduler/
COPY packages/worker/ /app/packages/worker/
COPY --from=protocol-builder /app/packages/backend/buf /app/packages/backend/buf
COPY --from=protocol-builder /app/packages/backend/dataforge_protocol /app/packages/backend/dataforge_protocol
COPY --from=protocol-builder /app/packages/scheduler/buf /app/packages/scheduler/buf
COPY --from=protocol-builder /app/packages/scheduler/dataforge_protocol /app/packages/scheduler/dataforge_protocol
COPY --from=protocol-builder /app/packages/worker/buf /app/packages/worker/buf
COPY --from=protocol-builder /app/packages/worker/dataforge_protocol /app/packages/worker/dataforge_protocol
COPY Justfile /app/Justfile
COPY scripts/ /app/scripts/

WORKDIR /app/packages/backend
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    if [ "$INSTALL_DEV" = "true" ]; then uv sync --frozen --group dev; else uv sync --frozen; fi && \
    apt-get purge -y --auto-remove build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY --from=frontend-builder /app/packages/frontend/build /app/packages/frontend/build

RUN mkdir -p /app/data/default/uploads /app/data/default/clean /app/data/default/exports /app/packages/backend/database && \
    chmod -R 755 /app/data /app/packages/backend/database

RUN chown -R appuser:appgroup /app

USER appuser
WORKDIR /app/packages/backend
ENV PATH="/app/packages/backend/.venv/bin:${PATH}"
EXPOSE 8000

FROM backend-base AS runtime-base
RUN chown -R appuser:appgroup /app/data /app/packages/backend/database

FROM runtime-base AS api
ENV PYTHONPATH="/app/packages/backend"
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready').status==200 else 1)"
CMD ["python3", "../backend/main.py"]

FROM runtime-base AS scheduler
ENV PYTHONPATH="/app/packages/scheduler"
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import main"
CMD ["python3", "../scheduler/main.py"]

FROM runtime-base AS worker
ENV PYTHONPATH="/app/packages/worker"
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import main"
CMD ["python3", "../worker/main.py"]
