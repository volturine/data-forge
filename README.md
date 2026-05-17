# Data-Forge Analysis Platform

> A local-first, no-code data analysis platform for building visual data pipelines — powered by Polars, FastAPI, and SvelteKit.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/volturine/data-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/volturine/data-forge/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Bun](https://img.shields.io/badge/runtime-Bun-black.svg)](https://bun.sh)

Data-Forge is a **local-first**, **no-code** data transformation tool. Build multi-step data pipelines visually, preview results instantly, schedule automated builds, and keep everything on your own machine — no cloud, no subscriptions, no data leaving your computer.

---

## Table of Contents

- [Data-Forge Analysis Platform](#data-forge-analysis-platform)
  - [Table of Contents](#table-of-contents)
  - [Features](#features)
  - [Tech Stack](#tech-stack)
  - [Quick Start](#quick-start)
    - [Option 1: Docker (Recommended)](#option-1-docker-recommended)
    - [Option 2: Local Development](#option-2-local-development)
  - [Configuration](#configuration)
    - [Production (Docker)](#production-docker)
    - [Development (local runtime)](#development-local-runtime)
    - [Key Variables](#key-variables)
  - [Development](#development)
    - [Prerequisites](#prerequisites)
    - [Commands](#commands)
    - [Running Tests](#running-tests)
    - [Code Style](#code-style)
  - [Project Structure](#project-structure)
  - [Architecture](#architecture)
    - [Compute Engine](#compute-engine)
    - [Pipeline Execution](#pipeline-execution)
    - [Scheduling](#scheduling)
    - [Storage Layout](#storage-layout)
  - [Roadmap](#roadmap)
  - [Contributing](#contributing)
  - [Security](#security)
    - [Development](#development-1)
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
| **Database** | PostgreSQL 18+ |
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

Docker has one production topology:

```text
postgres + api + scheduler + worker
```

The API container serves both the backend API and the built frontend on port 8000.

```bash
# 1) Edit docker/env/prod.env and set image tags, passwords, and secrets.
# 2) Start the production stack.
just docker-prod

# Open the application.
open http://localhost:8000
```

Equivalent raw Compose command:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod \
  -f docker/docker-compose.yml \
  up -d
```

For local image validation instead of pulling GHCR images:

```bash
just docker-prod-local
```

See [`docker/README.md`](docker/README.md) for the Docker production, evaluation, and development model.

### Option 2: Local Development

**Prerequisites:** Python 3.11+, [uv](https://github.com/astral-sh/uv), [Bun](https://bun.sh), [just](https://github.com/casey/just)

```bash
# Install all dependencies
just install

# Review packages/shared/dev.env for local settings

# Start the full local runtime with hot-reload
just dev
```

- Frontend: http://localhost:3000 (Vite dev server, proxies `/api` to backend)
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Background runtime: scheduler + dynamic build workers supervised by the local app runtime


---

## Configuration

### Production (Docker)

Production Docker deployments use `docker/docker-compose.yml` with `docker/env/prod.env`.
The API serves both the backend API and the pre-built frontend on port 8000.

```bash
just docker-prod
```

The repository defaults are tuned for concurrent clients:
- Docker production defaults to `4` API workers in the `api` service
- build throughput scales in the `worker` service up to `DF_BUILD_WORKER_MAX_PROCESSES`
- zero warm build workers are kept by default; worker subprocesses spawn on demand and exit when idle

### Development (local runtime)

Vite dev server on port 3000 proxies `/api` to FastAPI on port 8000. `just dev`
starts one supervised app runtime that runs API, scheduler, and dynamic build workers so queued builds do not run inside the API process.

```bash
just dev
```

### Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Enable debug logging and SQL echo |
| `PROD_MODE_ENABLED` | `false` | Serve static frontend from `packages/frontend/build` |
| `AUTH_REQUIRED` | `false` | Require login before accessing routes |
| `DATA_DIR` | — | Base directory for all data storage |
| `DATABASE_URL` | PostgreSQL connection URL | Runtime database connection |
| `DISTRIBUTED_RUNTIME_ENABLED` | `false` | Enables supported Postgres distributed runtime mode |
| `DEFAULT_NAMESPACE` | `default` | Default data namespace |

See **[docs/ENV_VARIABLES.md](docs/ENV_VARIABLES.md)** for the complete reference.

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
just dev            # Start supervised app runtime and frontend
just format         # Format all code (ruff + prettier)
just check          # Run ruff + mypy + svelte-check + eslint
just test           # Run backend pytest + frontend Vitest
just test-e2e       # Run Playwright end-to-end tests
just verify         # Format + static checks only
just prod           # Build frontend and start production server
```

### Running Tests

```bash
# Standard validation workflow
just verify
just test
just test-e2e
```

For code or config changes, run all three commands before opening a PR. For targeted local work, the tests live under `packages/shared/tests/`, `packages/backend/tests/`, `packages/scheduler/tests/`, `packages/worker-manager/tests/`, and `packages/frontend/tests/`.

### Code Style

- **Python**: Ruff (format + lint) + mypy — see `packages/backend/pyproject.toml`
- **TypeScript/Svelte**: ESLint + Prettier + svelte-check
- **Conventions**: See [STYLE_GUIDE.md](STYLE_GUIDE.md)

> **Important:** For code or config changes, run `just verify`, `just test`, and `just test-e2e` before opening a PR. All must pass with zero errors and zero unclassified warnings.

---

## Project Structure

```
data-forge/
├── packages/
│   ├── shared/               # Shared Python runtime, contracts, tests, and env files
│   ├── backend/              # FastAPI API service
│   ├── scheduler/            # Scheduler runtime
│   ├── worker-manager/       # Dynamic build worker runtime
│   └── frontend/             # SvelteKit frontend + Playwright/Vitest tests
├── docs/                     # Product docs, PRDs, and references
├── docker/                   # Docker image targets, compose, and env files
├── scripts/                  # Repo maintenance and validation scripts
├── Justfile                  # Task runner commands
├── AGENTS.md                 # Assistant workflow and repo rules
└── STYLE_GUIDE.md            # Code style conventions
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
3. Make your changes and run the required validation commands (`just verify`, `just test`, and `just test-e2e` for code/config changes)
4. Open a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines on code style, testing, and the review process.

---

## Security

If you discover a security vulnerability, please report it privately to the project maintainers.

**Do not open public issues for security vulnerabilities.**

### Development

- [docs/CHANGELOG.md](docs/CHANGELOG.md) — Release and project history
- [docs/ENV_VARIABLES.md](docs/ENV_VARIABLES.md) — Environment variable reference
- [docs/prd/data-forge.md](docs/prd/data-forge.md) — Core product spec and architecture
- [AGENTS.md](AGENTS.md) — Developer guidelines
- [STYLE_GUIDE.md](STYLE_GUIDE.md) — Code style
- [docs/prd/mcp-tool-contract.md](docs/prd/mcp-tool-contract.md) — How API routes are exposed as MCP tools
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
