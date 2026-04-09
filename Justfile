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

    BACKEND_PID=
    FRONTEND_PID=

    cleanup() {
        for pid in $BACKEND_PID $FRONTEND_PID; do
            [ -n "$pid" ] && kill -INT "$pid" 2>/dev/null || true
        done
        for pid in $BACKEND_PID $FRONTEND_PID; do
            [ -n "$pid" ] && wait "$pid" 2>/dev/null || true
        done
    }

    trap cleanup EXIT INT TERM

    set -a; source backend/e2e.env; set +a
    export FRONTEND_PORT=3001
    (cd backend && exec uv run --no-env-file ./main.py) &
    BACKEND_PID=$!
    (cd frontend && exec bun run dev) &
    FRONTEND_PID=$!

    for _ in {1..90}; do
        if curl -sf http://localhost:8001/health/ready >/dev/null 2>&1 \
            && curl -sf http://localhost:3001/ >/dev/null 2>&1; then
            cd frontend && PW_SERVERS_MANAGED=1 bun run test:e2e
            TEST_EXIT=$?
            cleanup
            trap - EXIT INT TERM
            exit $TEST_EXIT
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
