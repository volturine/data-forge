# Multi-stage Dockerfile for Data-Forge Analysis Platform
# Combines frontend and backend into a single deployable image

# ============================================
# Stage 1: Build Frontend
# ============================================
FROM oven/bun:1 AS frontend-builder

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

# ============================================
# Stage 2: Backend Runtime (Build + Run)
# ============================================
FROM python:3.13-slim AS backend-builder

WORKDIR /app/backend

# Install uv (from official image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

LABEL maintainer="Your Name <your.email@example.com>"
LABEL description="Data-Forge Analysis Platform - Combined frontend and backend"

# Create a custom user with UID 1000 and GID 1000
RUN addgroup --gid 1000 appgroup && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" appuser

# Copy dependency files
COPY backend/pyproject.toml backend/uv.lock* backend/README.md ./

# Install dependencies into .venv
RUN uv sync --frozen || uv sync

# Copy backend code
COPY backend/ /app/backend/

# Copy frontend build from builder
COPY --from=frontend-builder /app/frontend/build /app/frontend/build

# Create data directories with proper permissions
RUN mkdir -p /app/data/default/uploads /app/data/default/clean /app/data/default/exports /app/backend/database && \
    chmod -R 755 /app/data /app/backend/database

# Fix ownership and permissions for all files
RUN chown -R appuser:appgroup /app

USER appuser

# Change to backend directory for execution
WORKDIR /app/backend

# Expose port
EXPOSE 8000

# Health check using the /health endpoint
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# Start command using uv
CMD [ "uv", "run", "main.py" ]
