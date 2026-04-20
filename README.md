# Data-Forge Analysis Platform

> A local-first, no-code data analysis platform for building visual data pipelines — powered by Polars, FastAPI, and SvelteKit.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/volturine/polars-fastapi-svelte/actions/workflows/ci.yml/badge.svg)](https://github.com/volturine/polars-fastapi-svelte/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Bun](https://img.shields.io/badge/runtime-Bun-black.svg)](https://bun.sh)

Data-Forge is a **local-first**, **no-code** data transformation tool. Build multi-step data pipelines visually, preview results instantly, schedule automated builds, and keep everything on your own machine — no cloud, no subscriptions, no data leaving your computer.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Development](#development)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## Features

- **Visual Pipeline Builder** — Add, configure, and reorder transformation steps with immediate data preview
- **Multi-tab Analyses** — Organize related pipelines into tabs; tabs share a single compute engine run
- **Polars Performance** — All transformations execute as Polars LazyFrames, compiled to efficient query plans
- **Multiple Data Sources** — CSV, Excel, Parquet, JSON, DuckDB, external databases, and Apache Iceberg tables
- **Iceberg Storage** — Outputs materialized as Iceberg tables with time-travel snapshot support
- **Scheduling System** — Dataset-centric schedules: cron, dependency-based, and event-triggered rebuilds
- **Lineage Graph** — Visual graph showing datasource and analysis dependency relationships
- **Build Observability** — Full run history with request/response payloads, query plans, step timings, and run comparison
- **Namespace & Branch Architecture** — Isolated namespaces with per-datasource branch selection
- **MCP Tool Integration** — API routes exposed as Model Context Protocol tools for AI agent workflows
- **Notifications** — SMTP email and Telegram bot notifications on build events
- **Local-First** — Runs entirely on your machine; no cloud dependencies

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend Runtime** | Python 3.11+ with [uv](https://github.com/astral-sh/uv) |
| **API Framework** | FastAPI (async) |
| **Data Engine** | [Polars](https://pola.rs) + DuckDB |
| **Storage** | Apache Iceberg via [PyIceberg](https://py.iceberg.apache.org) |
| **Database** | SQLite with SQLAlchemy 2.0 async + Alembic migrations |
| **Schema Validation** | Pydantic V2 |
| **Frontend Runtime** | [Bun](https://bun.sh) |
| **UI Framework** | [SvelteKit 2](https://kit.svelte.dev) + [Svelte 5](https://svelte.dev) (runes mode) |
| **Type System** | TypeScript |
| **Styling** | [Panda CSS](https://panda-css.com) |
| **Data Fetching** | [TanStack Query](https://tanstack.com/query) |
| **Container** | Docker + Docker Compose |

---

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Copy and configure environment
cp .env.example .env

# Start with Docker Compose
docker compose up

# Open the application
open http://localhost:8000
```

### Option 2: Local Development

**Prerequisites:** Python 3.11+, [uv](https://github.com/astral-sh/uv), [Bun](https://bun.sh), [just](https://github.com/casey/just)

```bash
# Install all dependencies
just install

# Copy environment file
cp backend/.env.example backend/.env

# Start both servers with hot-reload
just dev
```

- Frontend: http://localhost:3000 (Vite dev server, proxies `/api` to backend)
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Install Prerequisites (Ubuntu/Debian)

```bash
./prerequisites.sh
```

---

## Configuration

The app supports two deployment topologies:

### Production (single port)

FastAPI serves both the API and the pre-built frontend on port 8000.

```bash
cp backend/.prod.env.example backend/.prod.env
# Edit .prod.env with your settings
cd frontend && bun run build
just prod
```

### Development (two servers)

Vite dev server on port 3000 proxies `/api` to FastAPI on port 8000.

```bash
just dev
```

### Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Enable debug logging and SQL echo |
| `PROD_MODE_ENABLED` | `false` | Serve static frontend from `frontend/build` |
| `ENGINE_IDLE_TIMEOUT` | `60` | Seconds before idle engines are cleaned up |
| `JOB_TIMEOUT` | `300` | Max job execution time in seconds |
| `AUTH_REQUIRED` | `false` | Require login before accessing routes |
| `DATA_DIR` | — | Base directory for all data storage |
| `DEFAULT_NAMESPACE` | `default` | Default data namespace |

See **[ENV_VARIABLES.md](ENV_VARIABLES.md)** for the complete reference.

---

## Development

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) — Python package manager
- [Bun](https://bun.sh) — JavaScript runtime and package manager
- [just](https://github.com/casey/just) — Command runner

### Commands

```bash
just install        # Install all dependencies
just dev            # Start both servers with hot-reload
just format         # Format all code (ruff + prettier)
just check          # Run all linters and type checks
just test           # Run backend pytest + frontend Vitest
just test-e2e       # Run Playwright end-to-end tests
just verify         # Full gate: format + check (required before every PR)
just prod           # Build frontend and start production server
```

### Running Tests

```bash
# Backend unit tests
cd backend && uv run pytest

# Frontend unit tests
cd frontend && bun run test:unit

# End-to-end tests (starts servers automatically)
just test-e2e
```

### Code Style

- **Python**: Ruff (format + lint) + mypy — see `backend/pyproject.toml`
- **TypeScript/Svelte**: ESLint + Prettier + svelte-check
- **Conventions**: See [STYLE_GUIDE.md](STYLE_GUIDE.md)

> **Important:** Always run `just verify` before opening a PR. It must pass with zero errors and zero warnings.

---

## Project Structure

```
polars-fastapi-svelte/
├── backend/                  # FastAPI Python backend
│   ├── api/                  # API route registration
│   ├── core/                 # Settings, database, lifespan
│   ├── modules/              # Feature modules (compute, datasources, analyses, ...)
│   │   ├── compute/          # Polars compute engine + process manager
│   │   ├── datasources/      # Data source CRUD and schema extraction
│   │   ├── analyses/         # Analysis and pipeline definition management
│   │   ├── scheduling/       # Dataset-centric scheduler
│   │   ├── lineage/          # Dependency graph computation
│   │   └── mcp/              # MCP tool registry and router
│   ├── tests/                # Backend pytest tests
│   └── main.py               # Application entry point
├── frontend/                 # SvelteKit frontend
│   ├── src/
│   │   ├── lib/              # Shared components, utils, stores
│   │   │   ├── components/   # Reusable UI components
│   │   │   ├── api/          # TanStack Query hooks
│   │   │   └── utils/        # Utility functions
│   │   └── routes/           # SvelteKit page routes
│   └── tests/                # Playwright e2e tests
├── docs/                     # Product and architecture docs
├── docker-compose.yml        # Docker Compose configuration
├── Dockerfile                # Production container image
├── Justfile                  # Task runner commands
└── ENV_VARIABLES.md          # Complete environment variable reference
```

---

## Architecture

### Compute Engine

Each analysis runs in an **isolated subprocess** (the "compute engine"). The main FastAPI process communicates with engines via multiprocessing queues. This provides:

- Memory isolation between analyses
- Configurable resource limits per engine
- Automatic cleanup of idle engines after a timeout
- WebSocket streaming of real-time compute status

### Pipeline Execution

A pipeline is a list of steps operating on a Polars LazyFrame. All tabs in an analysis are resolved in a **single engine run** — tab B can reference tab A's output as a LazyFrame without an intermediate disk write (intra-analysis dependency). Cross-analysis dependencies use materialized Iceberg snapshots.

### Scheduling

Schedules target **output datasets**, not analyses. At execution time the scheduler resolves:
`dataset → created_by_analysis_id → latest analysis version → tab → build`

This means schedule logic automatically picks up the latest analysis recipe without any version lock-in.

### Storage Layout

```
DATA_DIR/
├── app.db                          # Global settings database
└── namespaces/
    └── {namespace}/
        ├── namespace.db            # Per-namespace database
        ├── uploads/                # Raw uploaded files
        ├── clean/{uuid}/{branch}/  # Iceberg tables
        └── exports/                # Analysis output tables
```

---

## Roadmap

- [ ] Chart interactivity — tooltips, filter interactions, zoom
- [ ] Additional external database connectors
- [ ] Collaborative multi-user support
- [ ] Plugin/extension system for custom step types
- [ ] CLI for headless pipeline execution
- [ ] Export pipelines as standalone Python scripts

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes and run `just verify`
4. Open a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines on code style, testing, and the review process.

---

## Security

If you discover a security vulnerability, please report it responsibly. See [SECURITY.md](SECURITY.md) for details.

**Do not open public issues for security vulnerabilities.**

### Development

- **[IMPROVEMENTS.md](IMPROVEMENTS.md)** — Code quality improvements summary
- [PRD](docs/PRD.md) — Feature specs and architecture
- [AGENTS.md](AGENTS.md) — Developer guidelines
- [STYLE_GUIDE.md](STYLE_GUIDE.md) — Code style
- [MCP Tool Contract](docs/mcp-tool-contract.md) — How API routes are exposed as MCP tools
---

## License

MIT — see [LICENSE](LICENSE) for details.

---

## Acknowledgements

This project is built on top of excellent open-source software:

- [Polars](https://pola.rs) — Fast DataFrame library for Rust and Python
- [FastAPI](https://fastapi.tiangolo.com) — Modern, fast web framework for Python
- [SvelteKit](https://kit.svelte.dev) — Full-stack Svelte framework
- [Apache Iceberg](https://iceberg.apache.org) — Open table format for large datasets
- [PyIceberg](https://py.iceberg.apache.org) — Python implementation of Apache Iceberg
- [DuckDB](https://duckdb.org) — In-process analytical database
- [Panda CSS](https://panda-css.com) — CSS-in-JS with build-time generated styles
- [TanStack Query](https://tanstack.com/query) — Async state management for TypeScript
- [uv](https://github.com/astral-sh/uv) — Extremely fast Python package manager
- [Bun](https://bun.sh) — Fast all-in-one JavaScript runtime
