# Polars-FastAPI-Svelte Analysis Platform

A local-first, no-code data analysis tool for building data pipelines visually.

## Mission

Make data transformation and analysis accessible to people who aren't comfortable writing code, while still leveraging powerful tools like Polars under the hood. Runs entirely on your machine — no cloud, no subscriptions, no data leaving your computer.

## What This Is

- A visual pipeline builder for data transformations
- Support for CSV, Parquet, Excel, JSON, databases, and APIs
- Isolated compute environments (one analysis per process)
- Client-side schema calculation for instant feedback
- Built on Polars for performance

## Tech Stack

**Backend**: FastAPI + Python 3.13 + Polars + SQLAlchemy 2.0 (async) + SQLite + Pydantic V2

**Frontend**: SvelteKit 2 + Svelte 5 (runes) + TypeScript + TanStack Query

## Quick Start

```bash
# Install backend
cd backend
uv sync --extra dev

# Install frontend
cd ../frontend
npm install

# Run both
just dev
```

Frontend: http://localhost:5173

Backend: http://localhost:8000

## Documentation

- [PRD](docs/PRD.md) — Feature specs and architecture
- [AGENTS.md](AGENTS.md) — Developer guidelines
- [STYLE_GUIDE.md](STYLE_GUIDE.md) — Code style

## License

MIT
