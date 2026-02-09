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

# Build for production
prod:
    @echo "Building frontend..."
    cd frontend && npm run build
    @echo "Starting backend in production mode..."
    cd backend && uv run --env-file .prod.env ./main.py
