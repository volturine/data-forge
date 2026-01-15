# Data Analysis Platform - Master Task List

This is the **master task list** for the No-Code Data Analysis Platform. Tasks have been subdivided into parallel work streams in the `tasks/` subdirectories.

## Parallel Work Structure

```
                    ┌─────────────────────────────────────┐
                    │         0.0 Create Branch           │
                    └─────────────────┬───────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│   BACKEND TRACK     │   │   FRONTEND TRACK    │   │                     │
│                     │   │                     │   │                     │
│ 1.0 backend-core ◄──┼───┼── 6.0 frontend-     │   │                     │
│         │           │   │     infrastructure  │   │                     │
│         ▼           │   │         │           │   │                     │
│ ┌───────┴───────┐   │   │         ▼           │   │                     │
│ │               │   │   │ 7.0 frontend-api    │   │                     │
│ ▼               ▼   │   │         │           │   │                     │
│ 2.0            3.0  │   │         ▼           │   │                     │
│ datasource   analysis│   │ 8.0-9.0 stores &   │   │                     │
│ │               │   │   │   schema-calc       │   │                     │
│ └───────┬───────┘   │   │         │           │   │                     │
│         ▼           │   │    ┌────┴────┐      │   │                     │
│      4.0            │   │    ▼         ▼      │   │                     │
│    compute          │   │ 10-11     12-14     │   │                     │
│         │           │   │ gallery   viewers   │   │                     │
│         ▼           │   │ pages     pipeline  │   │                     │
│      5.0            │   │    └────┬────┘      │   │                     │
│    results          │   │         ▼           │   │                     │
│         │           │   │   15.0 editor       │   │                     │
│         │           │   │     + 16-17 UX      │   │                     │
└─────────┼───────────┘   └─────────┼───────────┘   │                     │
          │                         │               │                     │
          └─────────────────────────┼───────────────┘                     │
                                    ▼                                     │
                    ┌───────────────────────────────┐                     │
                    │  18.0-19.0 Integration Test   │                     │
                    │     & Documentation           │                     │
                    └───────────────────────────────┘
```

## Task Folders (Parallel Streams)

| Folder | Task | Dependencies | Can Parallelize With |
|--------|------|--------------|---------------------|
| [backend-core/](backend-core/) | 1.0 Backend Core Infrastructure | None | frontend-infrastructure |
| [backend-datasource/](backend-datasource/) | 2.0 Data Source Module | backend-core | backend-analysis, frontend-* |
| [backend-analysis/](backend-analysis/) | 3.0 Analysis Module | backend-core | backend-datasource, frontend-* |
| [backend-compute/](backend-compute/) | 4.0 Compute Engine Module | backend-core, backend-analysis, backend-datasource | frontend-* |
| [backend-results/](backend-results/) | 5.0 Results Module | backend-core, backend-compute | frontend-* |
| [frontend-infrastructure/](frontend-infrastructure/) | 6.0 Frontend Infrastructure | None | backend-* |
| [frontend-api/](frontend-api/) | 7.0 Frontend API Clients | frontend-infrastructure | backend-* |
| [frontend-stores/](frontend-stores/) | 8.0-9.0 Schema Calculator & Stores | frontend-infrastructure, frontend-api | frontend-viewers, frontend-pipeline |
| [frontend-gallery/](frontend-gallery/) | 10.0-11.0, 16.0 Gallery & Data Source Pages | frontend-stores | frontend-viewers, frontend-pipeline |
| [frontend-viewers/](frontend-viewers/) | 12.0 Data Viewers | frontend-infrastructure | frontend-gallery, frontend-pipeline |
| [frontend-pipeline/](frontend-pipeline/) | 13.0-14.0 Pipeline Builder | frontend-infrastructure, frontend-stores | frontend-viewers |
| [frontend-editor/](frontend-editor/) | 15.0, 17.0 Analysis Editor & UX | frontend-stores, frontend-viewers, frontend-pipeline | - |
| [integration-testing/](integration-testing/) | 18.0-19.0 Testing & Documentation | All modules | - |

## Recommended Team Allocation

### Team A: Backend (1-2 developers)
1. Start with `backend-core/` (blocking)
2. Then work on `backend-datasource/` and `backend-analysis/` in parallel
3. Then `backend-compute/`
4. Finally `backend-results/`

### Team B: Frontend (1-2 developers)
1. Start with `frontend-infrastructure/` (can start day 1)
2. Then `frontend-api/` (needs backend API contracts, not implementation)
3. Then `frontend-stores/` with schema calculator
4. Branch into:
   - One dev: `frontend-gallery/` and data source pages
   - Other dev: `frontend-viewers/` and `frontend-pipeline/`
5. Converge on `frontend-editor/`

### Team C: Integration (1 developer or both teams)
1. `integration-testing/` after all modules complete
2. Documentation and cleanup

---

## Relevant Files

### Backend - Core Infrastructure
- `backend/core/config.py` - Application configuration and settings
- `backend/core/database.py` - Async SQLAlchemy database setup
- `backend/core/__init__.py` - Core module exports

### Backend - Analysis Module
- `backend/modules/analysis/__init__.py` - Analysis module init
- `backend/modules/analysis/routes.py` - Analysis CRUD API endpoints
- `backend/modules/analysis/service.py` - Analysis business logic
- `backend/modules/analysis/schemas.py` - Pydantic models for analysis
- `backend/modules/analysis/models.py` - SQLAlchemy models for analysis

### Backend - Data Source Module
- `backend/modules/datasource/__init__.py` - Datasource module init
- `backend/modules/datasource/routes.py` - Data source API endpoints
- `backend/modules/datasource/service.py` - File upload, DB/API connection logic
- `backend/modules/datasource/schemas.py` - Pydantic models for data sources
- `backend/modules/datasource/models.py` - SQLAlchemy models for data sources

### Backend - Compute Module
- `backend/modules/compute/__init__.py` - Compute module init
- `backend/modules/compute/routes.py` - Compute execution endpoints
- `backend/modules/compute/service.py` - Compute manager service
- `backend/modules/compute/engine.py` - Polars subprocess engine
- `backend/modules/compute/schemas.py` - Pydantic models for compute jobs
- `backend/modules/compute/manager.py` - Process lifecycle management

### Backend - Results Module
- `backend/modules/results/__init__.py` - Results module init
- `backend/modules/results/routes.py` - Results retrieval endpoints
- `backend/modules/results/service.py` - Results storage/retrieval logic
- `backend/modules/results/schemas.py` - Pydantic models for results

### Backend - Tests
- `backend/tests/modules/analysis/test_routes.py` - Analysis API tests
- `backend/tests/modules/analysis/test_service.py` - Analysis service tests
- `backend/tests/modules/datasource/test_routes.py` - Datasource API tests
- `backend/tests/modules/datasource/test_service.py` - Datasource service tests
- `backend/tests/modules/compute/test_routes.py` - Compute API tests
- `backend/tests/modules/compute/test_engine.py` - Compute engine tests
- `backend/tests/modules/results/test_routes.py` - Results API tests

### Database
- `database/alembic.ini` - Alembic configuration
- `database/alembic/env.py` - Alembic environment setup
- `database/alembic/versions/` - Migration scripts directory

### Frontend - Pages
- `frontend/src/routes/+page.svelte` - Gallery/Home page
- `frontend/src/routes/analysis/[id]/+page.svelte` - Analysis editor page
- `frontend/src/routes/analysis/[id]/+page.ts` - Analysis page data loader
- `frontend/src/routes/analysis/new/+page.svelte` - New analysis wizard
- `frontend/src/routes/datasources/+page.svelte` - Data source management page
- `frontend/src/routes/datasources/new/+page.svelte` - Add data source page

### Frontend - Gallery Components
- `frontend/src/lib/components/gallery/AnalysisCard.svelte` - Analysis thumbnail card
- `frontend/src/lib/components/gallery/GalleryGrid.svelte` - Responsive grid layout
- `frontend/src/lib/components/gallery/AnalysisFilters.svelte` - Search/filter controls
- `frontend/src/lib/components/gallery/EmptyState.svelte` - Empty gallery state

### Frontend - Pipeline Components
- `frontend/src/lib/components/pipeline/PipelineCanvas.svelte` - Main pipeline builder canvas
- `frontend/src/lib/components/pipeline/StepNode.svelte` - Individual transformation step
- `frontend/src/lib/components/pipeline/StepConfig.svelte` - Step configuration panel
- `frontend/src/lib/components/pipeline/ConnectionLine.svelte` - Visual connections
- `frontend/src/lib/components/pipeline/StepLibrary.svelte` - Draggable operations palette

### Frontend - Operation Config Components
- `frontend/src/lib/components/operations/FilterConfig.svelte` - Filter step config
- `frontend/src/lib/components/operations/SelectConfig.svelte` - Column selection config
- `frontend/src/lib/components/operations/JoinConfig.svelte` - Join step config
- `frontend/src/lib/components/operations/GroupByConfig.svelte` - Aggregation config
- `frontend/src/lib/components/operations/SortConfig.svelte` - Sort step config
- `frontend/src/lib/components/operations/ExpressionConfig.svelte` - Custom expression config
- `frontend/src/lib/components/operations/MLModelConfig.svelte` - ML model config

### Frontend - Data Viewers
- `frontend/src/lib/components/viewers/DataTable.svelte` - Virtualized data table
- `frontend/src/lib/components/viewers/SchemaViewer.svelte` - Schema display
- `frontend/src/lib/components/viewers/StatsPanel.svelte` - Summary statistics
- `frontend/src/lib/components/viewers/DataChart.svelte` - Chart visualizations

### Frontend - Stores
- `frontend/src/lib/stores/analysis.svelte.ts` - Analysis state management
- `frontend/src/lib/stores/compute.svelte.ts` - Compute job state management
- `frontend/src/lib/stores/datasource.svelte.ts` - Data source state management

### Frontend - Schema Calculator
- `frontend/src/lib/utils/schema/schema-calculator.svelte.ts` - Client-side schema inference
- `frontend/src/lib/utils/schema/polars-types.ts` - Polars dtype definitions
- `frontend/src/lib/utils/schema/transformation-rules.ts` - Schema transformation rules

### Frontend - API Client
- `frontend/src/lib/api/client.ts` - Base API client with error handling
- `frontend/src/lib/api/analysis.ts` - Analysis API functions
- `frontend/src/lib/api/datasource.ts` - Data source API functions
- `frontend/src/lib/api/compute.ts` - Compute API functions
- `frontend/src/lib/api/results.ts` - Results API functions

### Frontend - Types
- `frontend/src/lib/types/analysis.ts` - Analysis type definitions
- `frontend/src/lib/types/datasource.ts` - Data source type definitions
- `frontend/src/lib/types/compute.ts` - Compute type definitions
- `frontend/src/lib/types/schema.ts` - Schema type definitions

### Frontend - Tests
- `frontend/src/lib/utils/schema/schema-calculator.test.ts` - Schema calculator tests
- `frontend/src/lib/api/client.test.ts` - API client tests

### Notes

- Backend follows RORO pattern (Receive Object, Return Object) with Pydantic models
- Frontend uses Svelte 5 runes (`$state`, `$derived`, `$effect`) - no legacy syntax
- All backend routes are async
- Database uses SQLite with async SQLAlchemy
- Use `just dev` to run both frontend and backend
- Use `pytest tests/ -v` for backend tests
- Use `npm run test` for frontend tests

---

## Instructions for Completing Tasks

**IMPORTANT:** As you complete each task, you must check it off in the **folder-specific task file** by changing `- [ ]` to `- [x]`. Also update this master list.

Each folder contains a `tasks-*.md` file with detailed sub-tasks. Work from those files and update them as you progress.

Example:
- `- [ ] 1.1 Read file` → `- [x] 1.1 Read file` (after completing)

---

## Master Task Summary

### Phase 1: Foundation (Parallel)

- [ ] **0.0 Create feature branch**
  - See: This file (below)

- [ ] **1.0 Backend Core Infrastructure**
  - See: [backend-core/tasks-backend-core.md](backend-core/tasks-backend-core.md)

- [ ] **6.0 Frontend Infrastructure**
  - See: [frontend-infrastructure/tasks-frontend-infrastructure.md](frontend-infrastructure/tasks-frontend-infrastructure.md)

### Phase 2: Core Modules (Parallel Backend + Frontend)

- [ ] **2.0 Data Source Module (Backend)**
  - See: [backend-datasource/tasks-backend-datasource.md](backend-datasource/tasks-backend-datasource.md)

- [ ] **3.0 Analysis Module (Backend)**
  - See: [backend-analysis/tasks-backend-analysis.md](backend-analysis/tasks-backend-analysis.md)

- [ ] **7.0 Frontend API Clients**
  - See: [frontend-api/tasks-frontend-api.md](frontend-api/tasks-frontend-api.md)

- [ ] **8.0-9.0 Schema Calculator & Stores**
  - See: [frontend-stores/tasks-frontend-stores.md](frontend-stores/tasks-frontend-stores.md)

### Phase 3: Advanced Modules (Parallel)

- [ ] **4.0 Compute Engine Module (Backend)**
  - See: [backend-compute/tasks-backend-compute.md](backend-compute/tasks-backend-compute.md)

- [ ] **5.0 Results Module (Backend)**
  - See: [backend-results/tasks-backend-results.md](backend-results/tasks-backend-results.md)

- [ ] **10.0-11.0, 16.0 Gallery & Pages**
  - See: [frontend-gallery/tasks-frontend-gallery.md](frontend-gallery/tasks-frontend-gallery.md)

- [ ] **12.0 Data Viewers**
  - See: [frontend-viewers/tasks-frontend-viewers.md](frontend-viewers/tasks-frontend-viewers.md)

- [ ] **13.0-14.0 Pipeline Builder**
  - See: [frontend-pipeline/tasks-frontend-pipeline.md](frontend-pipeline/tasks-frontend-pipeline.md)

### Phase 4: Integration (Sequential)

- [ ] **15.0, 17.0 Analysis Editor & UX Polish**
  - See: [frontend-editor/tasks-frontend-editor.md](frontend-editor/tasks-frontend-editor.md)

### Phase 5: Finalization

- [ ] **18.0-19.0 Testing & Documentation**
  - See: [integration-testing/tasks-integration-testing.md](integration-testing/tasks-integration-testing.md)

---

## Task 0: Create Feature Branch

- [ ] 0.0 Create feature branch
  - [ ] 0.1 Create and checkout a new branch: `git checkout -b feature/data-analysis-platform`

---

## Quick Reference: Commands

```bash
# Start development
just dev

# Backend tests
cd backend && pytest tests/ -v

# Frontend tests
cd frontend && npm run test

# Lint all
just lint

# Format all
just format

# Build frontend
just build
```

---

## Progress Tracking

| Module | Status | Completion |
|--------|--------|------------|
| 0.0 Feature Branch | ⬜ Not Started | 0% |
| 1.0 Backend Core | ⬜ Not Started | 0% |
| 2.0 Backend Datasource | ⬜ Not Started | 0% |
| 3.0 Backend Analysis | ⬜ Not Started | 0% |
| 4.0 Backend Compute | ⬜ Not Started | 0% |
| 5.0 Backend Results | ⬜ Not Started | 0% |
| 6.0 Frontend Infrastructure | ⬜ Not Started | 0% |
| 7.0 Frontend API | ⬜ Not Started | 0% |
| 8.0-9.0 Stores & Schema | ⬜ Not Started | 0% |
| 10.0-11.0, 16.0 Gallery & Pages | ⬜ Not Started | 0% |
| 12.0 Data Viewers | ⬜ Not Started | 0% |
| 13.0-14.0 Pipeline Builder | ⬜ Not Started | 0% |
| 15.0, 17.0 Editor & UX | ⬜ Not Started | 0% |
| 18.0-19.0 Testing & Docs | ⬜ Not Started | 0% |

Legend: ⬜ Not Started | 🟨 In Progress | ✅ Complete
