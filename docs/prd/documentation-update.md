# PRD: Documentation Update

## Overview

Overhaul project documentation to cover all environment variables, contribution guidelines, deployment instructions, and architecture overview. Consolidate scattered information into a well-structured, discoverable set of documents.

## Problem Statement

The project README references several documentation files that don't exist (DEPLOYMENT.md, ENV_VARIABLES.md, IMPROVEMENTS.md, CONTRIBUTING.md). Environment variables are only documented in `.env.example` with inline comments. There are no contribution guidelines for external contributors. New users and contributors face unnecessary friction getting started.

### Current State

| Document | Status |
|----------|--------|
| README.md | ✅ Exists, references missing docs |
| .env.example | ✅ 26+ variables with inline comments |
| CONTRIBUTING.md | ❌ Missing |
| ENV_VARIABLES.md | ❌ Missing (referenced in README) |
| DEPLOYMENT.md | ❌ Missing (referenced in README) |
| AGENTS.md | ✅ AI assistant guidelines |
| STYLE_GUIDE.md | ✅ Code standards |
| docs/PRD.md | ✅ Product requirements |
| Backend README | ✅ Setup and development |
| Frontend README | ⚠️ Generic SvelteKit template |
| API documentation | ❌ No OpenAPI docs page reference |
| Architecture overview | ⚠️ Excalidraw file only, no written doc |

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Complete README | All referenced documents exist; new user can set up in < 10 minutes |
| G-2 | Environment variable reference | Every env var documented with type, default, description, and example |
| G-3 | Contribution guidelines | External contributors can open a PR following documented process |
| G-4 | Deployment guide | Users can deploy via Docker, binary, or source with clear instructions |
| G-5 | Frontend-specific docs | Frontend README covers project-specific setup, not SvelteKit boilerplate |

## Non-Goals

- Generated API reference (FastAPI's `/docs` endpoint already provides this)
- Video tutorials or interactive guides
- Translated documentation (English only)
- Hosted documentation site (GitHub/GitLab markdown is sufficient)

## Deliverables

### D-1: README.md Overhaul

Update the root README to include:

1. **Project description** — One-paragraph summary of what Data-Forge is.
2. **Screenshots/GIFs** — Visual preview of the pipeline builder, datasource management, build history.
3. **Quick start** — Three paths: Docker (`docker compose up`), Binary (download + run), Source (clone + `just dev`).
4. **Configuration** — Link to ENV_VARIABLES.md with a summary table of the most important variables.
5. **Architecture** — High-level diagram (Mermaid or ASCII) showing frontend → backend → compute engine → storage.
6. **Tech stack** — Updated, accurate list with versions.
7. **Contributing** — Link to CONTRIBUTING.md.
8. **License** — License declaration.

Remove dead links to non-existent docs. Every link must resolve.

### D-2: ENV_VARIABLES.md

Comprehensive environment variable reference:

```markdown
## Application

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_NAME` | string | `"Data-Forge Analysis Platform"` | Display name |
| `DEBUG` | bool | `false` | Enable debug mode |
| `PORT` | int | `8000` | Server port |
...
```

Sections:
- Application
- Database
- CORS
- File Storage
- Polars Engine Resources
- Worker Configuration
- Engine Lifecycle
- Scheduler
- Job Management
- Filter Configuration
- Logging
- AI Providers
- Authentication
- Settings Encryption

Each variable includes:
- Name, type, default value, description
- Valid values or ranges where applicable
- Which variables require restart vs. hot-reload
- Cross-references (e.g., "See PostgreSQL Backend Support PRD for `DATABASE_URL` with PostgreSQL")

### D-3: CONTRIBUTING.md

Contribution guidelines covering:

1. **Getting started** — Fork, clone, `just install`, `just dev`.
2. **Development workflow** — Branch naming, commit messages, PR process.
3. **Code standards** — Link to STYLE_GUIDE.md with key highlights.
4. **Testing** — `just test` for unit tests, `just test-e2e` for end-to-end.
5. **Verification** — `just verify` must pass before submitting PR.
6. **PR template** — What to include in PR description.
7. **Issue reporting** — Bug report and feature request templates.
8. **Code of conduct** — Standard code of conduct reference.
9. **Architecture** — Link to docs/ for understanding the system before contributing.

### D-4: DEPLOYMENT.md

Deployment guide covering three methods:

1. **Docker Compose** (recommended)
   - Default (SQLite) setup
   - With PostgreSQL profile
   - With S3 storage (when available)
   - Environment variable configuration
   - Volume management
   - Updating to new versions

2. **Binary release**
   - Download from GitHub Releases
   - Platform-specific instructions (Linux, macOS, Windows)
   - Configuration via `.env` file
   - Running as a system service (systemd, launchd)

3. **From source**
   - Prerequisites (Python 3.13, Bun, Just)
   - Build steps
   - Production mode (`just prod`)

Common topics:
- Reverse proxy setup (nginx, Caddy) with example configs
- TLS/SSL configuration
- Backup and restore
- Monitoring and health checks

### D-5: Frontend README Update

Replace the generic SvelteKit README with project-specific content:

1. Prerequisites (Bun, Node.js version)
2. Setup (`bun install`, `bun run dev`)
3. Project structure (routes, components, stores)
4. Styling (Panda CSS, design tokens)
5. Type generation (`just generate-step-types`)
6. Testing (`bun test`, Playwright for e2e)
7. Build (`bun run build` → static output)

## Technical Approach

All documentation is Markdown files in the repository:

```
/
├── README.md              # Updated
├── CONTRIBUTING.md        # New
├── docs/
│   ├── ENV_VARIABLES.md   # New
│   ├── DEPLOYMENT.md      # New
│   └── ...existing docs
├── backend/README.md      # Minor updates
└── frontend/README.md     # Rewritten
```

### GitHub Templates

Add issue and PR templates:

```
.github/
├── ISSUE_TEMPLATE/
│   ├── bug_report.md
│   └── feature_request.md
└── PULL_REQUEST_TEMPLATE.md
```

## Acceptance Criteria

- [ ] README.md has no dead links — every referenced document exists
- [ ] ENV_VARIABLES.md documents every variable from `.env.example` with type, default, and description
- [ ] CONTRIBUTING.md covers fork → PR workflow with code standards and testing requirements
- [ ] DEPLOYMENT.md covers Docker, binary, and source deployment
- [ ] Frontend README is project-specific, not boilerplate
- [ ] GitHub issue templates exist for bugs and feature requests
- [ ] PR template exists with checklist
- [ ] `just verify` passes (no markdown lint errors if configured)