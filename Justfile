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

# Run all linters and type checks
check: 
    cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy .
    cd frontend && npx svelte-check --threshold warning && npm run lint

# Run backend tests
test:
    cd backend && uv run pytest --tb=short -q

# Full verification gate — must pass before any task is declared done
verify: format check

# Build for production
prod:
    @echo "Building frontend..."
    cd frontend && npm run build
    @echo "Starting backend in production mode..."
    cd backend && uv run --env-file .prod.env ./main.py
