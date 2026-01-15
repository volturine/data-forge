# PRD: No-Code Data Analysis Platform with Polars

**Project**: Polars-FastAPI-Svelte Analysis Platform
**Version**: 1.0.0
**Status**: Initial PRD
**Last Updated**: 2026-01-15

---

## 1. Overview

### Feature Summary
A single-user, no-code data analysis platform that enables complex data transformations, statistical analysis, and ML operations through a visual interface. The platform uses Polars as the compute engine, spawning isolated subprocess environments for each analysis to ensure system stability.

### User Value Proposition
- **No-code interface**: Build complex data pipelines without writing code
- **Palantir Contour-like UX**: Professional, intuitive data manipulation interface
- **Isolated compute**: Each analysis runs in a separate process, preventing crashes from affecting the main application
- **Local-first**: Runs on a single machine, no cloud dependencies
- **Performance**: Polars-powered compute for fast data processing
- **Flexibility**: Support for files, databases, and API data sources
- **Advanced capabilities**: ML models, statistical analysis, and custom transformations

### Success Criteria
- Users can create, save, and reopen analysis workflows
- Gallery view shows all past analyses with preview/metadata
- Opening an analysis spawns isolated Polars subprocess
- OOM or compute errors don't crash the main backend/frontend
- Frontend calculates schema changes locally without round-trips (except initial load/join)
- Sub-second response time for schema calculations
- Support for datasets up to memory limits (Polars lazy evaluation)

---

## 2. Technical Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (SvelteKit)                    │
│  - Analysis Gallery                                          │
│  - Pipeline Builder (Hybrid: Linear + DAG)                   │
│  - Schema Calculator (client-side)                           │
│  - Results Viewer                                            │
└───────────────────┬─────────────────────────────────────────┘
                    │ HTTP/WebSocket
┌───────────────────▼─────────────────────────────────────────┐
│                   Backend (FastAPI)                          │
│  - Analysis CRUD API                                         │
│  - Compute Manager (spawns/manages subprocesses)             │
│  - Data Source Connectors                                    │
│  - Result Aggregator                                         │
└───────────────────┬─────────────────────────────────────────┘
                    │ Process spawning
┌───────────────────▼─────────────────────────────────────────┐
│           Compute Engines (Polars Subprocesses)              │
│  - One subprocess per active analysis                        │
│  - Polars DataFrame operations                               │
│  - ML model execution                                        │
│  - Isolated memory space                                     │
└──────────────────────────────────────────────────────────────┘
```

### Backend Components

#### 2.1 Core Services

**Compute Manager Service** (`backend/modules/compute/service.py`)
- Spawn Polars subprocess for each analysis using `multiprocessing` or `subprocess`
- Manage subprocess lifecycle (start, monitor, terminate)
- Handle inter-process communication (IPC) via pipes/queues
- Kill stale processes on timeout
- Return process status and results

**Analysis Service** (`backend/modules/analysis/service.py`)
- CRUD operations for analysis definitions
- Store pipeline configuration as JSON
- Load/save analysis metadata
- Version control for analysis definitions

**Data Source Service** (`backend/modules/datasource/service.py`)
- Handle file uploads (CSV, Parquet, Excel, JSON)
- Database connections (PostgreSQL, MySQL, SQLite via Polars)
- API connectors (REST endpoints, authentication)
- Return schema information for sources

**Results Service** (`backend/modules/results/service.py`)
- Store computation results (parquet files or DB)
- Cache intermediate results
- Retrieve and serve result data
- Handle result pagination for large datasets

#### 2.2 API Endpoints

**Analysis Management**
```
POST   /api/v1/analysis          - Create new analysis
GET    /api/v1/analysis          - List all analyses (gallery)
GET    /api/v1/analysis/{id}     - Get analysis details
PUT    /api/v1/analysis/{id}     - Update analysis
DELETE /api/v1/analysis/{id}     - Delete analysis
POST   /api/v1/analysis/{id}/run - Execute analysis
GET    /api/v1/analysis/{id}/status - Get compute status
```

**Data Sources**
```
POST   /api/v1/datasource/upload      - Upload file
POST   /api/v1/datasource/connect     - Connect to DB/API
GET    /api/v1/datasource/{id}/schema - Get source schema
GET    /api/v1/datasource             - List data sources
DELETE /api/v1/datasource/{id}        - Delete source
```

**Compute Operations**
```
POST   /api/v1/compute/execute    - Execute pipeline step
POST   /api/v1/compute/preview    - Preview transformation (sample)
GET    /api/v1/compute/{job_id}/status - Job status
DELETE /api/v1/compute/{job_id}  - Cancel job
```

**Results**
```
GET    /api/v1/results/{analysis_id}        - Get results metadata
GET    /api/v1/results/{analysis_id}/data   - Get result data (paginated)
POST   /api/v1/results/{analysis_id}/export - Export results
```

#### 2.3 Pydantic Schemas

**Analysis Schemas** (`backend/modules/analysis/schemas.py`)
```python
class PipelineStepSchema(BaseModel):
    id: str
    type: str  # "filter", "select", "join", "groupby", "ml_model", etc.
    config: dict  # Step-specific configuration
    depends_on: list[str]  # Parent step IDs for DAG

class AnalysisCreateSchema(BaseModel):
    name: str
    description: str | None = None
    datasource_ids: list[str]
    pipeline_steps: list[PipelineStepSchema]

class AnalysisResponseSchema(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    datasource_ids: list[str]
    pipeline_steps: list[PipelineStepSchema]
    status: str  # "draft", "running", "completed", "error"
    result_id: str | None

class AnalysisGalleryItemSchema(BaseModel):
    id: str
    name: str
    thumbnail: str | None  # Base64 or URL to preview image
    created_at: datetime
    updated_at: datetime
    row_count: int | None
    column_count: int | None
```

**Compute Schemas** (`backend/modules/compute/schemas.py`)
```python
class ComputeExecuteSchema(BaseModel):
    analysis_id: str
    execute_mode: str  # "full", "preview", "step"
    step_id: str | None = None

class ComputeStatusSchema(BaseModel):
    job_id: str
    status: str  # "queued", "running", "completed", "error", "cancelled"
    progress: float  # 0.0 to 1.0
    current_step: str | None
    error_message: str | None
    process_id: int | None

class SchemaInfoSchema(BaseModel):
    columns: list[ColumnSchema]
    row_count: int | None

class ColumnSchema(BaseModel):
    name: str
    dtype: str  # Polars dtype string
    nullable: bool
```

**Data Source Schemas** (`backend/modules/datasource/schemas.py`)
```python
class DataSourceCreateSchema(BaseModel):
    name: str
    source_type: str  # "file", "database", "api"
    config: dict  # Type-specific config

class FileDataSourceConfig(BaseModel):
    file_path: str
    file_type: str  # "csv", "parquet", "excel", "json"
    options: dict  # Polars read options

class DatabaseDataSourceConfig(BaseModel):
    connection_string: str
    query: str

class APIDataSourceConfig(BaseModel):
    url: str
    method: str
    headers: dict | None
    auth: dict | None
```

#### 2.4 Database Models (SQLite + SQLAlchemy Async)

**Analysis Model** (`backend/modules/analysis/models.py`)
```python
class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str | None]
    pipeline_definition: Mapped[dict]  # JSON
    status: Mapped[str]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    result_path: Mapped[str | None]  # Path to parquet file
    thumbnail: Mapped[str | None]
```

**DataSource Model** (`backend/modules/datasource/models.py`)
```python
class DataSource(Base):
    __tablename__ = "datasources"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    source_type: Mapped[str]
    config: Mapped[dict]  # JSON
    schema_cache: Mapped[dict | None]  # Cached schema
    created_at: Mapped[datetime]
```

**AnalysisDataSource Association** (`backend/modules/analysis/models.py`)
```python
class AnalysisDataSource(Base):
    __tablename__ = "analysis_datasources"

    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), primary_key=True)
    datasource_id: Mapped[str] = mapped_column(ForeignKey("datasources.id"), primary_key=True)
```

### Frontend Components

#### 2.5 Page Structure

```
frontend/src/routes/
├── +page.svelte                    # Home/Gallery view
├── analysis/
│   ├── [id]/
│   │   ├── +page.svelte           # Analysis builder/editor
│   │   └── +page.ts               # Load analysis data
│   └── new/
│       └── +page.svelte           # New analysis wizard
└── datasources/
    ├── +page.svelte               # Data source management
    └── new/
        └── +page.svelte           # Add data source
```

#### 2.6 Core Components

**Gallery Components** (`frontend/src/lib/components/gallery/`)
- `AnalysisCard.svelte` - Thumbnail card with metadata
- `GalleryGrid.svelte` - Responsive grid layout
- `AnalysisFilters.svelte` - Search/filter controls

**Pipeline Builder** (`frontend/src/lib/components/pipeline/`)
- `PipelineCanvas.svelte` - Main canvas for building pipelines
- `StepNode.svelte` - Individual transformation step
- `StepConfig.svelte` - Configuration panel for steps
- `ConnectionLine.svelte` - Visual connections between steps
- `StepLibrary.svelte` - Draggable palette of operations

**Schema Calculator** (`frontend/src/lib/utils/schema/`)
- `schema-calculator.svelte.ts` - Client-side schema inference
- `polars-types.ts` - Type definitions matching Polars dtypes
- `transformation-rules.ts` - Schema transformation rules

**Data Viewers** (`frontend/src/lib/components/viewers/`)
- `DataTable.svelte` - Virtualized table for large datasets
- `DataChart.svelte` - Chart visualizations
- `SchemaViewer.svelte` - Column/type information display
- `StatsPanel.svelte` - Summary statistics

**Operation Configs** (`frontend/src/lib/components/operations/`)
- `FilterConfig.svelte` - Filter step configuration
- `SelectConfig.svelte` - Column selection
- `JoinConfig.svelte` - Join configuration
- `GroupByConfig.svelte` - Aggregation config
- `MLModelConfig.svelte` - ML model parameters

#### 2.7 State Management (Svelte 5 Runes)

**Analysis Store** (`frontend/src/lib/stores/analysis.svelte.ts`)
```typescript
import { writable } from 'svelte/store';

class AnalysisStore {
  current = $state<Analysis | null>(null);
  pipeline = $state<PipelineStep[]>([]);
  schema = $state<SchemaInfo | null>(null);

  loadAnalysis(id: string) { /* ... */ }
  addStep(step: PipelineStep) { /* ... */ }
  updateStep(id: string, updates: Partial<PipelineStep>) { /* ... */ }
  calculateSchema() { /* Client-side schema inference */ }
}

export const analysisStore = new AnalysisStore();
```

**Compute Store** (`frontend/src/lib/stores/compute.svelte.ts`)
```typescript
class ComputeStore {
  jobs = $state<Map<string, ComputeJob>>(new Map());

  executeAnalysis(id: string) { /* ... */ }
  pollJobStatus(jobId: string) { /* ... */ }
  cancelJob(jobId: string) { /* ... */ }
}
```

#### 2.8 API Client

**Base Client** (`frontend/src/lib/api/client.ts`)
- Fetch wrapper with error handling
- Type-safe API calls
- Request/response interceptors

**Resource Clients** (`frontend/src/lib/api/`)
- `analysis.ts` - Analysis CRUD operations
- `datasource.ts` - Data source operations
- `compute.ts` - Compute job management
- `results.ts` - Results fetching

---

## 3. Compute Isolation Architecture

### Subprocess Management

**Process Spawning Strategy**
```python
# backend/modules/compute/engine.py

import multiprocessing as mp
import polars as pl
from typing import Any

class PolarsComputeEngine:
    def __init__(self, analysis_id: str):
        self.analysis_id = analysis_id
        self.process: mp.Process | None = None
        self.result_queue = mp.Queue()
        self.command_queue = mp.Queue()

    def start(self):
        """Spawn isolated Polars subprocess"""
        self.process = mp.Process(
            target=self._run_compute,
            args=(self.command_queue, self.result_queue)
        )
        self.process.start()

    def _run_compute(self, cmd_queue: mp.Queue, result_queue: mp.Queue):
        """Runs in subprocess - isolated memory space"""
        try:
            while True:
                cmd = cmd_queue.get()
                if cmd['type'] == 'shutdown':
                    break

                # Execute Polars operations
                result = self._execute_pipeline(cmd['pipeline'])
                result_queue.put({'status': 'success', 'data': result})

        except Exception as e:
            result_queue.put({'status': 'error', 'error': str(e)})

    def execute(self, pipeline: dict) -> dict:
        """Send command to subprocess and wait for result"""
        self.command_queue.put({'type': 'execute', 'pipeline': pipeline})
        result = self.result_queue.get(timeout=300)  # 5 min timeout
        return result

    def shutdown(self):
        """Gracefully shutdown subprocess"""
        if self.process:
            self.command_queue.put({'type': 'shutdown'})
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.terminate()
```

**Process Manager** (`backend/modules/compute/manager.py`)
- Track all active compute processes
- Monitor memory/CPU usage
- Auto-kill processes on timeout
- Cleanup on analysis close
- Log subprocess errors without crashing main app

### Error Handling

**Subprocess Crash Handling**
1. Subprocess catches all exceptions
2. Sends error status to parent via queue
3. Parent logs error and updates job status
4. Frontend shows error without breaking UI
5. User can retry or modify pipeline

**OOM Protection**
- Set memory limits per subprocess (if supported)
- Monitor memory usage from parent
- Kill process before full system OOM
- Return "out of memory" error to user

---

## 4. Schema Calculation (Client-Side)

### Strategy

**Goal**: Minimize backend round-trips by calculating schema changes in the frontend

**Implementation**:
1. On analysis load: Fetch source schemas from backend
2. Store schemas in frontend state
3. As user adds transformation steps: Calculate output schema locally
4. Only fetch from backend for:
   - Initial data load
   - Join operations (need schema of second dataset)
   - Complex operations where local calculation is unreliable

**Schema Calculator** (`frontend/src/lib/utils/schema/schema-calculator.svelte.ts`)
```typescript
class SchemaCalculator {
  // Transformation rules
  applyFilter(schema: Schema, filter: FilterConfig): Schema {
    // Filtering doesn't change schema
    return schema;
  }

  applySelect(schema: Schema, columns: string[]): Schema {
    // Return only selected columns
    return {
      columns: schema.columns.filter(c => columns.includes(c.name))
    };
  }

  applyGroupBy(schema: Schema, config: GroupByConfig): Schema {
    // Group keys + aggregations
    const groupCols = config.groupBy.map(col =>
      schema.columns.find(c => c.name === col)
    );

    const aggCols = config.aggregations.map(agg => ({
      name: agg.alias || `${agg.column}_${agg.function}`,
      dtype: inferAggregationType(agg.function),
      nullable: false
    }));

    return { columns: [...groupCols, ...aggCols] };
  }

  async applyJoin(
    leftSchema: Schema,
    rightSchema: Schema,
    config: JoinConfig
  ): Promise<Schema> {
    // Fetch right schema if not cached
    if (!rightSchema) {
      rightSchema = await fetchSchema(config.rightDatasetId);
    }

    // Merge schemas based on join type
    // ...
  }
}
```

---

## 5. User Stories & Acceptance Criteria

### Epic 1: Analysis Gallery

**US-1.1: View Analysis Gallery**
- As a user, I want to see all my past analyses in a gallery view
- AC1: Gallery shows analysis cards with name, thumbnail, and metadata
- AC2: Cards display row count, column count, last updated date
- AC3: Empty state shows "Create your first analysis" message
- AC4: Gallery loads in <2 seconds for 100+ analyses

**US-1.2: Create New Analysis**
- As a user, I want to create a new analysis from the gallery
- AC1: "New Analysis" button opens wizard
- AC2: Wizard prompts for name and initial data source
- AC3: Successfully creates analysis and redirects to editor
- AC4: New analysis appears in gallery immediately

**US-1.3: Open Existing Analysis**
- As a user, I want to open a saved analysis
- AC1: Clicking card opens analysis in editor
- AC2: Backend spawns new Polars subprocess
- AC3: Frontend loads pipeline and schema
- AC4: Editor ready state shows within 3 seconds

**US-1.4: Delete Analysis**
- As a user, I want to delete analyses I no longer need
- AC1: Confirm dialog prevents accidental deletion
- AC2: Deletes analysis, results, and terminates subprocess
- AC3: Gallery updates immediately after deletion

### Epic 2: Data Source Management

**US-2.1: Upload File**
- As a user, I want to upload CSV/Parquet files
- AC1: Drag-and-drop or file picker
- AC2: Shows upload progress
- AC3: Validates file format
- AC4: Extracts and displays schema
- AC5: Supports files up to 10GB

**US-2.2: Connect to Database**
- As a user, I want to connect to databases (PostgreSQL, MySQL, SQLite)
- AC1: Form with connection string and test button
- AC2: Test connection before saving
- AC3: Browse tables/views
- AC4: Preview data sample
- AC5: Store connection securely (not in plaintext)

**US-2.3: Connect to API**
- As a user, I want to import data from REST APIs
- AC1: Configure URL, method, headers, auth
- AC2: Test request and preview response
- AC3: Map JSON to tabular format
- AC4: Handle pagination if needed

### Epic 3: Pipeline Builder

**US-3.1: Add Transformation Step**
- As a user, I want to add transformation steps to my pipeline
- AC1: Drag step from library onto canvas
- AC2: Step appears in linear sequence or as new node in DAG
- AC3: Configuration panel opens for step
- AC4: Schema updates immediately (client-side)

**US-3.2: Configure Filter Step**
- As a user, I want to filter rows based on conditions
- AC1: Select column, operator, value
- AC2: Support multiple conditions (AND/OR)
- AC3: Preview filtered row count
- AC4: Schema remains unchanged

**US-3.3: Configure Select Step**
- As a user, I want to select/drop columns
- AC1: Checkbox list of columns
- AC2: Reorder columns via drag-and-drop
- AC3: Rename columns inline
- AC4: Schema updates to show selected columns

**US-3.4: Configure Join Step**
- As a user, I want to join two datasets
- AC1: Select second dataset
- AC2: Choose join type (inner, left, right, outer)
- AC3: Map key columns
- AC4: Backend returns joined schema
- AC5: Preview shows sample joined rows

**US-3.5: Configure GroupBy Step**
- As a user, I want to aggregate data
- AC1: Select group-by columns
- AC2: Add aggregations (sum, mean, count, etc.)
- AC3: Name aggregated columns
- AC4: Schema updates to show group keys + aggregations

**US-3.6: Branch Pipeline (DAG Mode)**
- As a user, I want to create parallel transformation branches
- AC1: Right-click step to "Add branch"
- AC2: New node appears with connection to parent
- AC3: Each branch calculates schema independently
- AC4: Branches can merge via join/concat steps

**US-3.7: Configure ML Model Step**
- As a user, I want to apply ML models
- AC1: Select model type (linear regression, clustering, etc.)
- AC2: Choose feature columns and target column
- AC3: Set hyperparameters
- AC4: Execute training in subprocess
- AC5: Results include predictions column

### Epic 4: Execution & Results

**US-4.1: Execute Pipeline**
- As a user, I want to run my complete pipeline
- AC1: "Run" button triggers execution
- AC2: Backend spawns Polars subprocess
- AC3: Progress indicator shows current step
- AC4: Subprocess errors shown in UI, don't crash app
- AC5: Results stored and displayed on completion

**US-4.2: Preview Step**
- As a user, I want to preview results of a single step
- AC1: "Preview" button on step node
- AC2: Executes pipeline up to that step
- AC3: Shows sample rows (e.g., first 100)
- AC4: Does not save results

**US-4.3: View Results**
- As a user, I want to view computed results
- AC1: Results table with virtual scrolling
- AC2: Summary statistics panel
- AC3: Column sorting and filtering
- AC4: Chart visualizations (bar, line, scatter)

**US-4.4: Export Results**
- As a user, I want to export results
- AC1: Export to CSV, Parquet, Excel, JSON
- AC2: Download file to local machine
- AC3: Large files stream to prevent timeout

**US-4.5: Handle OOM Error**
- As a user, I want graceful handling of memory errors
- AC1: Subprocess crashes on OOM
- AC2: Parent process detects crash
- AC3: Error message shows in UI: "Analysis ran out of memory"
- AC4: Frontend and backend remain stable
- AC5: User can modify pipeline and retry

### Epic 5: Advanced Features

**US-5.1: Custom Expressions**
- As a user, I want to write custom Polars expressions
- AC1: Expression editor with syntax highlighting
- AC2: Validate expression before saving
- AC3: Support Polars API (pl.col(), pl.lit(), etc.)
- AC4: Show expression result type in schema

**US-5.2: Time Series Operations**
- As a user, I want to perform time series analysis
- AC1: Resample step (upsample/downsample)
- AC2: Rolling window aggregations
- AC3: Date range filtering
- AC4: Timezone handling

**US-5.3: Window Functions**
- As a user, I want to use window functions
- AC1: Rank, row_number, lead, lag operations
- AC2: Partition by columns
- AC3: Order by columns
- AC4: Schema includes new window columns

---

## 6. Edge Cases & Error Handling

### Edge Cases to Consider

1. **Empty Datasets**: Handle 0-row datasets gracefully
2. **Large Files**: Stream processing for files >1GB
3. **Schema Mismatches**: Clear error when join keys have different types
4. **Null Values**: Proper handling in aggregations and filters
5. **Type Coercion**: Explicit casting when needed
6. **Circular Dependencies**: Detect and prevent in DAG mode
7. **Orphan Steps**: Steps with no parent in DAG
8. **Concurrent Edits**: Prevent race conditions when saving

### Error Categories

**Frontend Errors**:
- Schema calculation failures → Show validation error
- Invalid configuration → Highlight problematic fields
- Network errors → Retry with exponential backoff

**Backend Errors**:
- File not found → 404 with clear message
- Database connection failed → Test connection, show diagnostic info
- Subprocess spawn failed → Log error, return 500

**Subprocess Errors**:
- OOM → Catch, log, return error status
- Polars exceptions → Catch, return user-friendly message
- Timeout → Kill process after 5 minutes, return timeout error

---

## 7. Implementation Notes

### Svelte 5 Patterns

- Use `$state` for reactive variables
- Use `$derived` for computed values (e.g., schema calculation)
- Use `$effect` for side effects (e.g., autosave)
- Components use runes, not `let` or `$:` syntax
- Stores use `.svelte.ts` extension for runes compatibility

### Async Patterns

- Backend: All routes are `async def`
- Services return Pydantic models wrapped in `Result[T, Error]` (RORO)
- Use `asyncio` for concurrent operations
- Database queries use `async with` session context

### Type Safety

- Backend: Pydantic V2 with strict validation
- Frontend: TypeScript strict mode
- Shared types via OpenAPI schema generation
- Runtime validation at API boundaries

### Security Considerations

- Single-user app: No authentication required
- File uploads: Validate file types, size limits
- Database connections: Sanitize connection strings
- SQL injection: Use parameterized queries
- Path traversal: Validate file paths
- Subprocess isolation: Prevent code injection

### Performance Considerations

- Lazy evaluation: Use Polars lazy API for large datasets
- Streaming: Stream results for large outputs
- Caching: Cache data source schemas
- Virtualization: Virtual scroll for large tables
- Debouncing: Debounce schema calculations on config changes

---

## 8. Testing Strategy

### Unit Tests

**Backend Tests** (pytest)
- Test each service method independently
- Mock database and subprocess calls
- Test Pydantic schema validation
- Test error handling

**Frontend Tests** (Vitest)
- Test schema calculator logic
- Test component rendering
- Test state management
- Test API client

### Integration Tests

**API Tests**
- Test full request/response cycle
- Test database integration
- Test file upload flow
- Test subprocess spawning

**E2E Tests** (Playwright)
- Create analysis end-to-end
- Add and configure steps
- Execute pipeline
- View results
- Error handling flows

### Manual Testing Scenarios

1. **Happy Path**: Create analysis, add steps, execute, view results
2. **OOM Simulation**: Large dataset that exceeds memory, verify graceful handling
3. **Complex Pipeline**: 20+ steps in DAG mode, verify performance
4. **Data Source Variety**: Test CSV, Parquet, DB, API sources
5. **Browser Compatibility**: Test on Chrome, Firefox, Safari
6. **Error Recovery**: Simulate various errors, verify UI remains stable

---

## 9. Database Schema

### Tables

**analyses**
```sql
CREATE TABLE analyses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    pipeline_definition JSON NOT NULL,
    status TEXT NOT NULL,  -- draft, running, completed, error
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    result_path TEXT,
    thumbnail TEXT
);
```

**datasources**
```sql
CREATE TABLE datasources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,  -- file, database, api
    config JSON NOT NULL,
    schema_cache JSON,
    created_at TIMESTAMP NOT NULL
);
```

**analysis_datasources** (many-to-many)
```sql
CREATE TABLE analysis_datasources (
    analysis_id TEXT NOT NULL,
    datasource_id TEXT NOT NULL,
    PRIMARY KEY (analysis_id, datasource_id),
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
    FOREIGN KEY (datasource_id) REFERENCES datasources(id) ON DELETE CASCADE
);
```

**compute_jobs** (optional, for job tracking)
```sql
CREATE TABLE compute_jobs (
    id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- queued, running, completed, error, cancelled
    progress REAL DEFAULT 0.0,
    current_step TEXT,
    error_message TEXT,
    process_id INTEGER,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
);
```

---

## 10. Critical Files to Create/Modify

### Backend Files

**New Modules**
```
backend/modules/analysis/
  ├── routes.py           # Analysis CRUD endpoints
  ├── service.py          # Analysis business logic
  ├── schemas.py          # Pydantic models
  └── models.py           # SQLAlchemy models

backend/modules/datasource/
  ├── routes.py           # Data source endpoints
  ├── service.py          # Connection/upload logic
  ├── schemas.py          # Pydantic models
  └── models.py           # SQLAlchemy models

backend/modules/compute/
  ├── routes.py           # Compute endpoints
  ├── service.py          # Compute manager
  ├── engine.py           # Polars subprocess engine
  └── schemas.py          # Pydantic models

backend/modules/results/
  ├── routes.py           # Results endpoints
  ├── service.py          # Results storage/retrieval
  └── schemas.py          # Pydantic models
```

**Database Setup**
```
backend/core/
  ├── database.py         # Async SQLAlchemy setup
  └── config.py           # App configuration

database/
  └── alembic/           # Migration scripts
```

### Frontend Files

**Pages**
```
frontend/src/routes/
  ├── +page.svelte                    # Gallery
  ├── analysis/[id]/+page.svelte      # Analysis editor
  ├── analysis/new/+page.svelte       # New analysis wizard
  └── datasources/+page.svelte        # Data source management
```

**Components**
```
frontend/src/lib/components/
  ├── gallery/
  │   ├── AnalysisCard.svelte
  │   └── GalleryGrid.svelte
  ├── pipeline/
  │   ├── PipelineCanvas.svelte
  │   ├── StepNode.svelte
  │   └── StepLibrary.svelte
  ├── viewers/
  │   ├── DataTable.svelte
  │   └── SchemaViewer.svelte
  └── operations/
      ├── FilterConfig.svelte
      ├── JoinConfig.svelte
      └── GroupByConfig.svelte
```

**Utils & Stores**
```
frontend/src/lib/
  ├── stores/
  │   ├── analysis.svelte.ts
  │   └── compute.svelte.ts
  ├── utils/schema/
  │   ├── schema-calculator.svelte.ts
  │   └── transformation-rules.ts
  └── api/
      ├── client.ts
      ├── analysis.ts
      ├── datasource.ts
      └── compute.ts
```

---

## 11. Verification & Testing

### End-to-End Verification

1. **Start Application**
   ```bash
   just dev
   ```

2. **Create Analysis**
   - Navigate to gallery (homepage)
   - Click "New Analysis"
   - Upload CSV file
   - Verify schema displays correctly

3. **Build Pipeline**
   - Add filter step
   - Add select columns step
   - Add group by step
   - Verify schema updates after each step (without backend calls)

4. **Execute Pipeline**
   - Click "Run Analysis"
   - Verify progress indicator
   - Check backend logs for subprocess spawn
   - Verify results display

5. **Test Error Handling**
   - Create pipeline with large dataset (if available)
   - Verify OOM error is caught
   - Check that frontend and backend remain responsive
   - Verify error message displays in UI

6. **Test Gallery**
   - Return to homepage
   - Verify analysis appears with thumbnail
   - Open analysis again
   - Verify pipeline loads correctly

### Automated Tests

**Backend**
```bash
cd backend
pytest tests/ -v --cov
```

**Frontend**
```bash
cd frontend
npm run test:unit
npm run test:e2e
```

### Performance Benchmarks

- Gallery load time: <2s for 100 analyses
- Schema calculation: <100ms per step
- Pipeline execution: Depends on data size (use Polars benchmarks)
- Result table rendering: 60fps with virtual scroll

---

## 12. Future Enhancements (Out of Scope for V1)

- **Collaboration**: Multi-user support, shared analyses
- **Scheduling**: Automated pipeline execution
- **Version Control**: Analysis versioning with diffs
- **Data Lineage**: Visual lineage tracking
- **Custom Connectors**: Plugin system for new data sources
- **Real-time Updates**: WebSocket-based live execution updates
- **Cloud Deployment**: Multi-instance deployment with load balancing
- **Advanced ML**: AutoML, model registry, experiment tracking
- **Governance**: Data quality rules, validation checks
- **Monitoring**: Compute resource usage, performance metrics

---

## Appendix: Technology Stack Summary

**Backend**
- FastAPI 0.100+
- Python 3.13
- Polars (latest)
- SQLAlchemy 2.0 (async)
- SQLite
- Pydantic V2
- uvicorn
- pytest

**Frontend**
- SvelteKit 5
- Svelte 5 (runes)
- TypeScript 5+
- TanStack Query (to be added)
- Vite
- Vitest (testing)
- Playwright (e2e)

**DevOps**
- uv (Python package manager)
- Just (task runner)
- Ruff (Python linting)
- Prettier (JS/TS formatting)
- Git
