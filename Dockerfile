# Multi-stage Dockerfile for Polars-FastAPI-Svelte Analysis Platform
# Combines frontend and backend into a single deployable image

# ============================================
# Stage 1: Build Frontend
# ============================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

# Copy package files
COPY frontend/package*.json ./

# Install dependencies
RUN npm ci --omit=dev

# Copy frontend source
COPY frontend/ .

# Build static site
# The build will be output to /app/frontend/build
RUN npm run build

# ============================================
# Stage 2: Build Backend Dependencies
# ============================================
FROM python:3.13-slim AS backend-builder

WORKDIR /app/backend

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY backend/pyproject.toml backend/uv.lock* ./

# Install dependencies into .venv
RUN uv sync --frozen --no-dev || uv sync --no-dev

# ============================================
# Stage 3: Runtime Image
# ============================================
FROM python:3.13-slim

LABEL maintainer="Your Name <your.email@example.com>"
LABEL description="Polars-FastAPI-Svelte Analysis Platform - Combined frontend and backend"

WORKDIR /app

# Install runtime dependencies
# - curl: for health checks
# - ca-certificates: for HTTPS requests
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy backend code
COPY backend/ /app/backend/

# Copy virtual environment from builder
COPY --from=backend-builder /app/backend/.venv /app/backend/.venv

# Copy frontend build from builder
COPY --from=frontend-builder /app/frontend/build /app/frontend/build

# Set up environment
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create data directories with proper permissions
RUN mkdir -p /app/data/uploads /app/data/results /app/data/exports /app/backend/database && \
    chmod -R 755 /app/data /app/backend/database

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Change to backend directory for execution
WORKDIR /app/backend

# Expose port
EXPOSE 8000

# Health check using the /health endpoint
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start command using Gunicorn with Uvicorn workers
CMD ["gunicorn", "main:app", \
     "-c", "gunicorn.conf.py", \
     "-b", "0.0.0.0:8000"]
