# Justfile for Svelte-FastAPI Template

# Default goal
default: dev

# Install all dependencies
install:
    @echo "Installing backend dependencies..."
    cd backend && uv sync
    @echo "Installing frontend dependencies..."
    cd frontend && npm install

# Run development servers concurrently
dev:
    @echo "Starting servers..."
    (cd backend && uv run --env-file .env ./main.py) & (cd frontend && npm run dev) & wait

# Format code
format:
    @echo "Formatting backend..."
    cd backend && uv run ruff format .
    @echo "Formatting frontend..."
    cd frontend && npm run format

# Lint backend (ruff + mypy)
lint-backend:
    cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy .

# Lint frontend (svelte-check + prettier + eslint)
lint-frontend:
    cd frontend && npx svelte-check --threshold warning && npm run lint

# Run all linters and type checks
check: lint-backend lint-frontend

# Run backend tests
test:
    cd backend && uv run pytest --tb=short -q

# Full verification gate — must pass before any task is declared done
verify: format test check

# Build for production
prod:
    @echo "Building frontend..."
    cd frontend && npm run build
    @echo "Starting backend in production mode..."
    cd backend && uv run --env-file .prod.env ./main.py
