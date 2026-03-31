# Justfile for Svelte-FastAPI Template

# Default goal
default: dev

# Install all dependencies
install:
    @echo "Installing backend dependencies..."
    cd backend && uv sync
    @echo "Installing frontend dependencies..."
    cd frontend && bun install

# Run development servers concurrently
dev:
    @echo "Starting servers..."
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
        lsof -ti tcp:8000,3000 | xargs kill 2>/dev/null || true
    }

    trap cleanup EXIT INT TERM

    (cd backend && uv run --env-file e2e.env ./main.py) &
    (cd frontend && bun run dev) &
    FRONTEND_PID=$!

    for _ in {1..90}; do
        if nc -z localhost 8000 && nc -z localhost 3000; then
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
verify: format check

# Build for production
prod:
    @echo "Building frontend..."
    cd frontend && bun run build
    @echo "Starting backend in production mode..."
    cd backend && uv run --env-file .prod.env ./main.py
