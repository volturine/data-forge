# Justfile for Svelte-FastAPI Template

# Default goal
default: dev

# Install all dependencies
install:
    @echo "Installing backend dependencies..."
    cd backend && uv sync
    @echo "Installing frontend dependencies..."
    cd frontend && bun install

# Update dependencies to latest available versions
update-deps:
    @echo "Updating backend dependencies to latest..."
    cd backend && uv lock --upgrade && uv sync
    @echo "Updating frontend dependencies to latest..."
    cd frontend && bun update --latest

# Run development servers concurrently
dev:
    #!/usr/bin/env bash
    set -a; source backend/.env; set +a
    (cd backend && uv run --env-file .env ./main.py) & (cd frontend && bun run dev) & wait

# Format code
format:
    @echo "Formatting backend..."
    cd backend && uv run ruff format .
    @echo "Formatting frontend..."
    cd frontend && bun run format

# Run all linters and type checks
check:
    cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy .
    cd frontend && bun run panda:codegen && bun run check && bun run lint


# Run e2e tests with backend + frontend lifecycle managed by Just
test-e2e:
    #!/usr/bin/env bash
    set -euo pipefail

    cleanup() {
        lsof -ti tcp:8001,3001 | xargs kill 2>/dev/null || true
    }

    trap cleanup EXIT INT TERM

    set -a; source backend/e2e.env; set +a
    (cd backend && uv run --no-env-file ./main.py) &
    (cd frontend && bun run dev) &
    FRONTEND_PID=$!

    for _ in {1..90}; do
        if nc -z localhost 8001 && nc -z localhost 3001; then
            cd frontend && bun run test:e2e
            exit 0
        fi
        sleep 1
    done

    echo "Timed out waiting for backend/frontend to start for e2e tests" >&2
    exit 1

# Run backend tests
test:
    cd backend && uv run pytest --tb=short -q
    cd frontend && bun run test:unit

# Generate TypeScript types from Pydantic step schemas
generate-step-types:
    cd backend && uv run python scripts/generate_ts_step_types.py

# Full verification gate -- must pass before any task is declared done
verify: format check test

# Build for production (single-port: FastAPI serves the built frontend)
# Setup: cp backend/.prod.env.example backend/.prod.env  then edit it.
prod:
    @echo "Building frontend..."
    cd frontend && bun run build
    @echo "Starting backend in production mode..."
    cd backend && uv run --env-file .prod.env ./main.py
