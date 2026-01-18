# Polars-FastAPI-Svelte Analysis Platform

## Technical Documentation

Welcome to the comprehensive technical documentation for the **Polars-FastAPI-Svelte Analysis Platform** - a sophisticated, local-first data analysis application that enables users to build visual data transformation pipelines without writing code.

---

## Quick Links

| Section | Description |
|---------|-------------|
| [Architecture](./architecture/README.md) | System design, patterns, data flow |
| [Backend](./backend/README.md) | FastAPI, modules, database, compute engine |
| [Frontend](./frontend/README.md) | SvelteKit, components, state management |
| [API Reference](./api/README.md) | Endpoints, schemas, examples |
| [Guides](./guides/README.md) | Getting started, development, deployment |
| [Reference](./reference/README.md) | Types, operations, configuration |
| [Contributing](./contributing/README.md) | Code style, architecture decisions |

---

## Project Overview

### What is this project?

The Polars-FastAPI-Svelte Analysis Platform is a full-stack data analysis application that combines:

- **Visual Pipeline Builder**: Drag-and-drop interface for constructing data transformations
- **High-Performance Processing**: Polars-powered backend for efficient data operations
- **Modern Reactive UI**: Svelte 5 with real-time schema prediction
- **Local-First Design**: All computation and data stays on your machine

### Key Characteristics

| Aspect | Description |
|--------|-------------|
| **Architecture** | Monorepo with clear frontend/backend separation |
| **Paradigm** | Local-first, no cloud dependency |
| **Data Processing** | Polars lazy evaluation for memory efficiency |
| **Computation** | Isolated multiprocessing engines per analysis |
| **State Management** | Svelte 5 runes with TanStack Query |
| **Type Safety** | TypeScript (frontend) + Pydantic (backend) |

### Core Capabilities

1. **Data Source Management**
   - Upload files (CSV, Parquet, Excel, JSON, NDJSON)
   - Connect to databases (SQLite, PostgreSQL, MySQL)
   - Connect to REST APIs

2. **Visual Pipeline Builder**
   - Drag-and-drop operation nodes
   - Real-time schema preview
   - 20+ transformation operations

3. **Supported Operations**
   - Filtering, Selection, Sorting
   - Grouping and Aggregation
   - Joins, Pivots, Unpivots
   - String transformations
   - Time series operations
   - And more...

4. **Result Management**
   - Paginated data viewing
   - Export to multiple formats
   - Schema inspection

---

## Technology Stack

### Backend

| Component | Technology | Purpose |
|-----------|------------|---------|
| Framework | FastAPI | Async web framework |
| Language | Python 3.13 | Runtime |
| ORM | SQLAlchemy 2.0+ | Async database |
| Database | SQLite | Embedded storage |
| Validation | Pydantic 2.0+ | Data validation |
| Data Processing | Polars | High-performance DataFrames |
| Migrations | Alembic | Schema versioning |
| Package Manager | UV | Fast dependency management |

### Frontend

| Component | Technology | Purpose |
|-----------|------------|---------|
| Framework | SvelteKit 2 | Full-stack framework |
| UI Library | Svelte 5 | Reactive components |
| Build Tool | Vite 7 | Fast bundling |
| Language | TypeScript 5 | Type safety |
| Data Fetching | TanStack Query | Server state |
| UI Primitives | Melt UI | Accessible components |
| Testing | Vitest | Unit testing |

### Development

| Tool | Purpose |
|------|---------|
| Just | Task automation |
| Ruff | Python linting/formatting |
| ESLint | TypeScript linting |
| Prettier | Code formatting |
| GitLab CI | Continuous integration |

---

## Documentation Structure

```
docs/
├── README.md                    # This file
├── architecture/                # System architecture
│   ├── README.md               # Architecture overview
│   ├── system-design.md        # High-level design
│   ├── design-patterns.md      # Patterns used
│   ├── data-flow.md            # Data flow diagrams
│   └── technology-decisions.md # ADRs
│
├── backend/                     # Backend documentation
│   ├── README.md               # Backend overview
│   ├── application.md          # FastAPI application
│   ├── modules/                # Module documentation
│   │   ├── README.md
│   │   ├── analysis.md
│   │   ├── datasource.md
│   │   ├── compute.md
│   │   ├── results.md
│   │   └── health.md
│   ├── database/               # Database documentation
│   │   ├── README.md
│   │   ├── setup.md
│   │   ├── models.md
│   │   ├── migrations.md
│   │   └── queries.md
│   └── compute-engine/         # Compute engine docs
│       ├── README.md
│       ├── architecture.md
│       ├── operations.md
│       └── pipeline-execution.md
│
├── frontend/                    # Frontend documentation
│   ├── README.md               # Frontend overview
│   ├── sveltekit-structure.md  # SvelteKit structure
│   ├── styling.md              # Design system
│   ├── components/             # Component documentation
│   │   ├── README.md
│   │   ├── pipeline/
│   │   ├── operations/
│   │   ├── viewers/
│   │   └── gallery/
│   ├── state-management/       # State documentation
│   │   └── README.md
│   └── api-client/             # API client documentation
│       └── README.md
│
├── api/                         # API documentation
│   ├── README.md               # API overview
│   ├── endpoints/              # Endpoint documentation
│   │   └── README.md
│   └── schemas/                # Schema documentation
│       └── README.md
│
├── guides/                      # User guides
│   ├── README.md               # Guides index
│   ├── getting-started.md      # Quick start
│   ├── development-workflow.md # Dev workflow
│   ├── creating-datasources.md # Adding data sources
│   ├── building-pipelines.md   # Pipeline tutorial
│   ├── testing.md              # Testing guide
│   └── adding-operations.md    # Extending operations
│
├── reference/                   # Reference documentation
│   ├── README.md               # Reference index
│   ├── configuration.md        # All configuration
│   ├── type-definitions.md     # TypeScript types
│   └── polars-operations.md    # All operations
│
└── contributing/                # Contribution guides
    └── README.md               # Contributing overview
```

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/volturine/polars-fastapi-svelte.git
cd polars-fastapi-svelte

# Install dependencies
just install

# Run database migrations
cd backend && ./migrate.sh upgrade && cd ..

# Start development servers
just dev

# Access the application
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

For detailed setup instructions, see the [Getting Started Guide](./guides/getting-started.md).

---

## Development Commands

| Command | Description |
|---------|-------------|
| `just install` | Install all dependencies |
| `just dev` | Run development servers |
| `just lint` | Check code quality |
| `just format` | Auto-format code |
| `just build` | Build frontend for production |

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SvelteKit Frontend                               │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────────┐ │
│  │   Gallery    │  │   Pipeline   │  │   Data Source Manager          │ │
│  │   View       │  │   Editor     │  │                                │ │
│  └──────────────┘  └──────────────┘  └────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    State (Svelte Runes + TanStack Query)            ││
│  └─────────────────────────────────────────────────────────────────────┘│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ HTTP/REST
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Backend                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Analysis │  │Datasource│  │ Compute  │  │ Results  │  │  Health  │  │
│  │  Module  │  │  Module  │  │  Module  │  │  Module  │  │  Module  │  │
│  └──────────┘  └──────────┘  └────┬─────┘  └──────────┘  └──────────┘  │
└───────────────────────────────────┼─────────────────────────────────────┘
                                    │ Multiprocessing
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Polars Compute Engine (Subprocess)                    │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │  LazyFrame → Filter → Select → GroupBy → ... → Collect → Result    ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           Storage Layer                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│  │   SQLite DB      │  │   Upload Files   │  │   Result Files   │      │
│  │   (Metadata)     │  │   (Raw Data)     │  │   (Parquet)      │      │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## License

MIT License

---

## Support

- **Issues**: [GitHub Issues](https://github.com/volturine/polars-fastapi-svelte/issues)
- **Discussions**: [GitHub Discussions](https://github.com/volturine/polars-fastapi-svelte/discussions)
