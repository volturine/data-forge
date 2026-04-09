# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Chart interactivity: tooltips, filter interactions, and zoom controls
- Additional data source connectors

### Changed

- Performance improvements for large dataset previews

### Fixed

- Various UI polish and accessibility improvements

---

## [1.0.0] - 2024-01-01

### Added

#### Core Platform
- Visual pipeline builder with drag-and-drop step configuration
- Multi-tab analysis editor with per-tab pipelines
- Analysis gallery with list, search, sort, and create/delete operations
- Version history for analyses — restore and rename versions

#### Compute Engine
- Isolated multiprocess compute engine per analysis (one subprocess per analysis)
- Polars-based data transformation with LazyFrame execution
- Unified DAG execution: all tabs in an analysis resolved in a single engine run
- Intra-analysis LazyFrame passthrough — no intermediate datasource reloads
- Configurable engine idle timeout and job timeout

#### Data Sources
- CSV ingestion with configurable delimiter and re-ingest on settings change
- Excel ingestion with preflight sheet detection
- Parquet, JSON, and DuckDB source support
- Apache Iceberg table storage with time-travel snapshot selection
- External database ingestion with stored connection details
- Datasource registration from existing Iceberg paths
- Provenance tracking: raw import vs. analysis-created distinction

#### Scheduling System
- Dataset-centric scheduling: schedules target output datasets, not analyses
- Cron-based time triggers (e.g., daily, weekly)
- Dependency triggers: wait for another schedule to complete
- Event triggers: run when an upstream datasource updates
- Scheduler resolves latest analysis version at execution time

#### Lineage and Observability
- Lineage graph rendering datasource and analysis dependency edges
- Build/preview run history with filter by kind, status, date, and search
- Run detail expansion: request payload, result, query plan, step timings
- Side-by-side run comparison: row diffs, schema diffs, timing diffs

#### Namespace and Branch Architecture
- Multi-namespace support with per-namespace isolated databases and directories
- Single DATA_DIR environment variable with auto-derived subdirectories
- Branch-aware datasources: select target branch per datasource input
- Lineage filtered by output datasource and branch

#### UDF Library
- User-defined function (UDF) creation and management
- UDFs available in transformation step expressions

#### Notifications
- SMTP email notification configuration
- Telegram bot integration with lifecycle management
- Per-build and per-step notification pathways

#### Settings
- Runtime-configurable global settings via settings popup
- SMTP and Telegram credentials persisted in database with encryption support
- Authentication support with configurable required/optional modes

#### API and Integration
- FastAPI async REST API with Pydantic V2 request/response schemas
- WebSocket-based real-time compute status streaming
- MCP (Model Context Protocol) tool integration — API routes exposed as AI tools
- OpenAPI documentation auto-generated

#### Infrastructure
- Docker and Docker Compose production deployment
- Single-container deployment: FastAPI serves pre-built frontend on one port
- Two-topology support: single-port production and dual-server development
- SQLAlchemy 2.0 async SQLite persistence
- Alembic database migrations
- Graceful shutdown with resource cleanup
- Configurable worker count and resource limits

#### Developer Experience
- `just` command runner with verify, format, check, test, dev, prod targets
- Ruff linting and formatting for Python
- mypy type checking for Python
- ESLint + Prettier for TypeScript/Svelte
- svelte-check for Svelte type safety
- Vitest unit tests for frontend utilities
- Playwright end-to-end tests
- Panda CSS design system with semantic tokens

[Unreleased]: https://github.com/volturine/polars-fastapi-svelte/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/volturine/polars-fastapi-svelte/releases/tag/v1.0.0
