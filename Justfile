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

# Run backend tests
test:
    cd backend && uv run pytest --tb=short -q

# Generate TypeScript types from Pydantic step schemas
generate-step-types:
    cd backend && uv run python scripts/generate_ts_step_types.py

# Full verification gate -- must pass before any task is declared done
verify: format check

# Run frontend e2e tests (requires both servers running: just dev)
test-e2e:
    cd frontend && bun run test:e2e

# Build for production
prod:
    @echo "Building frontend..."
    cd frontend && bun run build
    @echo "Starting backend in production mode..."
    cd backend && uv run --env-file .prod.env ./main.py
