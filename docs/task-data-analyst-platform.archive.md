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

## Instructions for Completing Tasks

**IMPORTANT:** As you complete each task, you must check it off in this markdown file by changing `- [ ]` to `- [x]`. This helps track progress and ensures you don't skip any steps.

Example:

- `- [ ] 1.1 Read file` → `- [x] 1.1 Read file` (after completing)

Update the file after completing each sub-task, not just after completing an entire parent task.

## Tasks

- [ ] 0.0 Create feature branch
  - [ ] 0.1 Create and checkout a new branch for this feature (`git checkout -b feature/data-analysis-platform`)

- [ ] 1.0 Setup Backend Core Infrastructure
  - [ ] 1.1 Create `backend/core/config.py` with application settings (database URL, upload directory, etc.)
  - [ ] 1.2 Create `backend/core/database.py` with async SQLAlchemy engine and session management
  - [ ] 1.3 Add required dependencies to `backend/pyproject.toml` (polars, sqlalchemy[asyncio], aiosqlite, alembic, python-multipart)
  - [ ] 1.4 Setup Alembic for database migrations in `database/` directory
  - [ ] 1.5 Create initial migration with all tables (analyses, datasources, analysis_datasources, compute_jobs)
  - [ ] 1.6 Update `backend/main.py` to initialize database on startup
  - [ ] 1.7 Create `backend/core/__init__.py` exporting config and database utilities

- [ ] 2.0 Implement Data Source Module (Backend)
  - [ ] 2.1 Create `backend/modules/datasource/models.py` with DataSource SQLAlchemy model
  - [ ] 2.2 Create `backend/modules/datasource/schemas.py` with Pydantic schemas (DataSourceCreate, DataSourceResponse, FileConfig, DatabaseConfig, APIConfig, SchemaInfo, ColumnSchema)
  - [ ] 2.3 Create `backend/modules/datasource/service.py` with functions for:
    - [ ] 2.3.1 `create_file_datasource()` - Handle file upload and store metadata
    - [ ] 2.3.2 `create_database_datasource()` - Validate and store DB connection
    - [ ] 2.3.3 `create_api_datasource()` - Store API configuration
    - [ ] 2.3.4 `get_datasource_schema()` - Extract schema using Polars
    - [ ] 2.3.5 `list_datasources()` - List all data sources
    - [ ] 2.3.6 `delete_datasource()` - Delete data source and associated files
  - [ ] 2.4 Create `backend/modules/datasource/routes.py` with API endpoints:
    - [ ] 2.4.1 `POST /api/v1/datasource/upload` - File upload endpoint
    - [ ] 2.4.2 `POST /api/v1/datasource/connect` - Database/API connection endpoint
    - [ ] 2.4.3 `GET /api/v1/datasource` - List all data sources
    - [ ] 2.4.4 `GET /api/v1/datasource/{id}/schema` - Get schema for data source
    - [ ] 2.4.5 `DELETE /api/v1/datasource/{id}` - Delete data source
  - [ ] 2.5 Register datasource router in `backend/api/v1/__init__.py`
  - [ ] 2.6 Write unit tests for datasource service in `backend/tests/modules/datasource/test_service.py`
  - [ ] 2.7 Write API tests for datasource routes in `backend/tests/modules/datasource/test_routes.py`

- [ ] 3.0 Implement Analysis Module (Backend)
  - [ ] 3.1 Create `backend/modules/analysis/models.py` with Analysis and AnalysisDataSource SQLAlchemy models
  - [ ] 3.2 Create `backend/modules/analysis/schemas.py` with Pydantic schemas (PipelineStep, AnalysisCreate, AnalysisUpdate, AnalysisResponse, AnalysisGalleryItem)
  - [ ] 3.3 Create `backend/modules/analysis/service.py` with functions for:
    - [ ] 3.3.1 `create_analysis()` - Create new analysis with initial pipeline
    - [ ] 3.3.2 `get_analysis()` - Get analysis by ID with full pipeline
    - [ ] 3.3.3 `list_analyses()` - List all analyses for gallery view
    - [ ] 3.3.4 `update_analysis()` - Update analysis pipeline and metadata
    - [ ] 3.3.5 `delete_analysis()` - Delete analysis and associated results
    - [ ] 3.3.6 `link_datasource()` - Associate data source with analysis
  - [ ] 3.4 Create `backend/modules/analysis/routes.py` with API endpoints:
    - [ ] 3.4.1 `POST /api/v1/analysis` - Create new analysis
    - [ ] 3.4.2 `GET /api/v1/analysis` - List all analyses
    - [ ] 3.4.3 `GET /api/v1/analysis/{id}` - Get analysis details
    - [ ] 3.4.4 `PUT /api/v1/analysis/{id}` - Update analysis
    - [ ] 3.4.5 `DELETE /api/v1/analysis/{id}` - Delete analysis
  - [ ] 3.5 Register analysis router in `backend/api/v1/__init__.py`
  - [ ] 3.6 Write unit tests for analysis service in `backend/tests/modules/analysis/test_service.py`
  - [ ] 3.7 Write API tests for analysis routes in `backend/tests/modules/analysis/test_routes.py`

- [ ] 4.0 Implement Compute Engine Module (Backend)
  - [ ] 4.1 Create `backend/modules/compute/schemas.py` with Pydantic schemas (ComputeExecute, ComputeStatus, ComputeResult)
  - [ ] 4.2 Create `backend/modules/compute/engine.py` with PolarsComputeEngine class:
    - [ ] 4.2.1 Implement `start()` - Spawn isolated subprocess
    - [ ] 4.2.2 Implement `_run_compute()` - Main subprocess loop with Polars operations
    - [ ] 4.2.3 Implement `execute()` - Send pipeline command and await result
    - [ ] 4.2.4 Implement `shutdown()` - Graceful subprocess termination
    - [ ] 4.2.5 Implement `_execute_pipeline()` - Execute Polars transformations from pipeline definition
  - [ ] 4.3 Create `backend/modules/compute/manager.py` with ProcessManager class:
    - [ ] 4.3.1 Implement process tracking (dict of analysis_id -> engine)
    - [ ] 4.3.2 Implement `get_or_create_engine()` - Get existing or spawn new engine
    - [ ] 4.3.3 Implement `shutdown_engine()` - Terminate specific engine
    - [ ] 4.3.4 Implement `shutdown_all()` - Terminate all engines on app shutdown
    - [ ] 4.3.5 Implement health monitoring and stale process cleanup
  - [ ] 4.4 Create `backend/modules/compute/service.py` with functions for:
    - [ ] 4.4.1 `execute_analysis()` - Run full pipeline and store results
    - [ ] 4.4.2 `preview_step()` - Execute up to specific step with sample data
    - [ ] 4.4.3 `get_job_status()` - Get compute job status
    - [ ] 4.4.4 `cancel_job()` - Cancel running job
  - [ ] 4.5 Create `backend/modules/compute/routes.py` with API endpoints:
    - [ ] 4.5.1 `POST /api/v1/analysis/{id}/run` - Execute analysis
    - [ ] 4.5.2 `GET /api/v1/analysis/{id}/status` - Get compute status
    - [ ] 4.5.3 `POST /api/v1/compute/preview` - Preview transformation
    - [ ] 4.5.4 `DELETE /api/v1/compute/{job_id}` - Cancel job
  - [ ] 4.6 Register compute router in `backend/api/v1/__init__.py`
  - [ ] 4.7 Add process manager shutdown hook to app lifespan
  - [ ] 4.8 Write tests for compute engine in `backend/tests/modules/compute/test_engine.py`
  - [ ] 4.9 Write API tests for compute routes in `backend/tests/modules/compute/test_routes.py`

- [ ] 5.0 Implement Results Module (Backend)
  - [ ] 5.1 Create `backend/modules/results/schemas.py` with Pydantic schemas (ResultMetadata, ResultData, ExportRequest)
  - [ ] 5.2 Create `backend/modules/results/service.py` with functions for:
    - [ ] 5.2.1 `store_result()` - Save Polars DataFrame to parquet file
    - [ ] 5.2.2 `get_result_metadata()` - Get row/column counts and schema
    - [ ] 5.2.3 `get_result_data()` - Get paginated result data
    - [ ] 5.2.4 `export_result()` - Export to CSV/Parquet/Excel/JSON
    - [ ] 5.2.5 `delete_result()` - Delete result files
  - [ ] 5.3 Create `backend/modules/results/routes.py` with API endpoints:
    - [ ] 5.3.1 `GET /api/v1/results/{analysis_id}` - Get result metadata
    - [ ] 5.3.2 `GET /api/v1/results/{analysis_id}/data` - Get paginated data
    - [ ] 5.3.3 `POST /api/v1/results/{analysis_id}/export` - Export results
  - [ ] 5.4 Register results router in `backend/api/v1/__init__.py`
  - [ ] 5.5 Write tests for results routes in `backend/tests/modules/results/test_routes.py`

- [ ] 6.0 Setup Frontend Infrastructure
  - [ ] 6.1 Install required dependencies (`npm install @tanstack/svelte-query`)
  - [ ] 6.2 Create `frontend/src/lib/types/analysis.ts` with TypeScript types matching backend schemas
  - [ ] 6.3 Create `frontend/src/lib/types/datasource.ts` with data source types
  - [ ] 6.4 Create `frontend/src/lib/types/compute.ts` with compute job types
  - [ ] 6.5 Create `frontend/src/lib/types/schema.ts` with schema types
  - [ ] 6.6 Create `frontend/src/lib/api/client.ts` with base fetch wrapper and error handling
  - [ ] 6.7 Setup TanStack Query provider in `frontend/src/routes/+layout.svelte`

- [ ] 7.0 Implement Frontend API Clients
  - [ ] 7.1 Create `frontend/src/lib/api/analysis.ts` with functions:
    - [ ] 7.1.1 `createAnalysis()` - POST to create analysis
    - [ ] 7.1.2 `listAnalyses()` - GET all analyses for gallery
    - [ ] 7.1.3 `getAnalysis()` - GET single analysis by ID
    - [ ] 7.1.4 `updateAnalysis()` - PUT to update analysis
    - [ ] 7.1.5 `deleteAnalysis()` - DELETE analysis
  - [ ] 7.2 Create `frontend/src/lib/api/datasource.ts` with functions:
    - [ ] 7.2.1 `uploadFile()` - POST file upload with FormData
    - [ ] 7.2.2 `connectDatabase()` - POST database connection
    - [ ] 7.2.3 `connectApi()` - POST API connection
    - [ ] 7.2.4 `listDatasources()` - GET all data sources
    - [ ] 7.2.5 `getDatasourceSchema()` - GET schema for data source
    - [ ] 7.2.6 `deleteDatasource()` - DELETE data source
  - [ ] 7.3 Create `frontend/src/lib/api/compute.ts` with functions:
    - [ ] 7.3.1 `executeAnalysis()` - POST to run analysis
    - [ ] 7.3.2 `getComputeStatus()` - GET job status
    - [ ] 7.3.3 `previewStep()` - POST to preview transformation
    - [ ] 7.3.4 `cancelJob()` - DELETE to cancel job
  - [ ] 7.4 Create `frontend/src/lib/api/results.ts` with functions:
    - [ ] 7.4.1 `getResultMetadata()` - GET result info
    - [ ] 7.4.2 `getResultData()` - GET paginated data
    - [ ] 7.4.3 `exportResult()` - POST to export
  - [ ] 7.5 Write tests for API client in `frontend/src/lib/api/client.test.ts`

- [ ] 8.0 Implement Schema Calculator (Frontend)
  - [ ] 8.1 Create `frontend/src/lib/utils/schema/polars-types.ts` with Polars dtype definitions and TypeScript mappings
  - [ ] 8.2 Create `frontend/src/lib/utils/schema/transformation-rules.ts` with schema transformation rules for each operation type
  - [ ] 8.3 Create `frontend/src/lib/utils/schema/schema-calculator.svelte.ts` with SchemaCalculator class:
    - [ ] 8.3.1 Implement `applyFilter()` - Filter doesn't change schema
    - [ ] 8.3.2 Implement `applySelect()` - Return selected columns
    - [ ] 8.3.3 Implement `applyRename()` - Update column names
    - [ ] 8.3.4 Implement `applyGroupBy()` - Group keys + aggregation columns
    - [ ] 8.3.5 Implement `applyJoin()` - Merge schemas based on join type
    - [ ] 8.3.6 Implement `applySort()` - Sort doesn't change schema
    - [ ] 8.3.7 Implement `applyExpression()` - Add new computed column
    - [ ] 8.3.8 Implement `calculatePipelineSchema()` - Apply all steps sequentially
  - [ ] 8.4 Write comprehensive tests in `frontend/src/lib/utils/schema/schema-calculator.test.ts`

- [ ] 9.0 Implement Frontend Stores
  - [ ] 9.1 Create `frontend/src/lib/stores/analysis.svelte.ts` with AnalysisStore class using Svelte 5 runes:
    - [ ] 9.1.1 Define `$state` for current analysis, pipeline steps, source schemas
    - [ ] 9.1.2 Define `$derived` for calculated schema (using SchemaCalculator)
    - [ ] 9.1.3 Implement `loadAnalysis()` - Fetch and set current analysis
    - [ ] 9.1.4 Implement `addStep()` - Add transformation step
    - [ ] 9.1.5 Implement `updateStep()` - Update step configuration
    - [ ] 9.1.6 Implement `removeStep()` - Remove step from pipeline
    - [ ] 9.1.7 Implement `reorderSteps()` - Reorder pipeline steps
    - [ ] 9.1.8 Implement `save()` - Save analysis to backend
  - [ ] 9.2 Create `frontend/src/lib/stores/compute.svelte.ts` with ComputeStore class:
    - [ ] 9.2.1 Define `$state` for active jobs map
    - [ ] 9.2.2 Implement `executeAnalysis()` - Start execution and poll status
    - [ ] 9.2.3 Implement `pollJobStatus()` - Periodic status updates
    - [ ] 9.2.4 Implement `cancelJob()` - Cancel running job
  - [ ] 9.3 Create `frontend/src/lib/stores/datasource.svelte.ts` with DatasourceStore class:
    - [ ] 9.3.1 Define `$state` for data sources list
    - [ ] 9.3.2 Implement `loadDatasources()` - Fetch all data sources
    - [ ] 9.3.3 Implement `uploadFile()` - Handle file upload
    - [ ] 9.3.4 Implement `getSchema()` - Get schema for data source

- [ ] 10.0 Implement Gallery Page (Frontend)
  - [ ] 10.1 Create `frontend/src/lib/components/gallery/AnalysisCard.svelte`:
    - [ ] 10.1.1 Display analysis name, thumbnail, and metadata
    - [ ] 10.1.2 Show row count, column count, last updated date
    - [ ] 10.1.3 Add click handler to navigate to analysis editor
    - [ ] 10.1.4 Add delete button with confirmation
  - [ ] 10.2 Create `frontend/src/lib/components/gallery/GalleryGrid.svelte`:
    - [ ] 10.2.1 Implement responsive CSS grid layout
    - [ ] 10.2.2 Accept analyses array as prop
    - [ ] 10.2.3 Render AnalysisCard for each analysis
  - [ ] 10.3 Create `frontend/src/lib/components/gallery/AnalysisFilters.svelte`:
    - [ ] 10.3.1 Add search input for name filtering
    - [ ] 10.3.2 Add sort dropdown (name, date, size)
  - [ ] 10.4 Create `frontend/src/lib/components/gallery/EmptyState.svelte`:
    - [ ] 10.4.1 Display "Create your first analysis" message
    - [ ] 10.4.2 Add prominent "New Analysis" button
  - [ ] 10.5 Update `frontend/src/routes/+page.svelte`:
    - [ ] 10.5.1 Fetch analyses using TanStack Query
    - [ ] 10.5.2 Render GalleryGrid or EmptyState based on data
    - [ ] 10.5.3 Add "New Analysis" button in header
    - [ ] 10.5.4 Implement loading and error states

- [ ] 11.0 Implement New Analysis Wizard (Frontend)
  - [ ] 11.1 Create `frontend/src/routes/analysis/new/+page.svelte`:
    - [ ] 11.1.1 Step 1: Enter analysis name and description
    - [ ] 11.1.2 Step 2: Select or upload initial data source
    - [ ] 11.1.3 Step 3: Preview schema of selected data source
    - [ ] 11.1.4 Submit: Create analysis and redirect to editor
  - [ ] 11.2 Create data source selection component with:
    - [ ] 11.2.1 List of existing data sources
    - [ ] 11.2.2 File upload drop zone
    - [ ] 11.2.3 Database connection form
    - [ ] 11.2.4 API connection form

- [ ] 12.0 Implement Data Viewers (Frontend)
  - [ ] 12.1 Create `frontend/src/lib/components/viewers/SchemaViewer.svelte`:
    - [ ] 12.1.1 Display columns with name, type, nullable status
    - [ ] 12.1.2 Add type icons for different Polars dtypes
    - [ ] 12.1.3 Show column count in header
  - [ ] 12.2 Create `frontend/src/lib/components/viewers/DataTable.svelte`:
    - [ ] 12.2.1 Implement virtual scrolling for large datasets
    - [ ] 12.2.2 Display column headers with type indicators
    - [ ] 12.2.3 Support column sorting on click
    - [ ] 12.2.4 Handle loading and error states
    - [ ] 12.2.5 Implement pagination controls
  - [ ] 12.3 Create `frontend/src/lib/components/viewers/StatsPanel.svelte`:
    - [ ] 12.3.1 Display row count, column count
    - [ ] 12.3.2 Show column statistics (min, max, mean, null count)
  - [ ] 12.4 Create `frontend/src/lib/components/viewers/DataChart.svelte`:
    - [ ] 12.4.1 Support bar, line, scatter chart types
    - [ ] 12.4.2 Column selection for X and Y axes
    - [ ] 12.4.3 Basic chart rendering (can use Chart.js or similar)

- [ ] 13.0 Implement Operation Config Components (Frontend)
  - [ ] 13.1 Create `frontend/src/lib/components/operations/FilterConfig.svelte`:
    - [ ] 13.1.1 Column dropdown (from current schema)
    - [ ] 13.1.2 Operator dropdown (=, !=, >, <, >=, <=, contains, etc.)
    - [ ] 13.1.3 Value input (type-aware based on column dtype)
    - [ ] 13.1.4 Add/remove multiple conditions with AND/OR toggle
  - [ ] 13.2 Create `frontend/src/lib/components/operations/SelectConfig.svelte`:
    - [ ] 13.2.1 Checkbox list of all columns
    - [ ] 13.2.2 Select all / deselect all buttons
    - [ ] 13.2.3 Drag-and-drop column reordering
    - [ ] 13.2.4 Inline rename capability
  - [ ] 13.3 Create `frontend/src/lib/components/operations/JoinConfig.svelte`:
    - [ ] 13.3.1 Data source selector for right side
    - [ ] 13.3.2 Join type dropdown (inner, left, right, outer)
    - [ ] 13.3.3 Key column mapping (left column → right column)
    - [ ] 13.3.4 Column name conflict resolution (suffix)
  - [ ] 13.4 Create `frontend/src/lib/components/operations/GroupByConfig.svelte`:
    - [ ] 13.4.1 Multi-select for group-by columns
    - [ ] 13.4.2 Add aggregation: column + function (sum, mean, count, min, max, etc.)
    - [ ] 13.4.3 Alias input for aggregated columns
    - [ ] 13.4.4 Remove aggregation button
  - [ ] 13.5 Create `frontend/src/lib/components/operations/SortConfig.svelte`:
    - [ ] 13.5.1 Add sort columns with ascending/descending toggle
    - [ ] 13.5.2 Drag-and-drop to reorder sort priority
  - [ ] 13.6 Create `frontend/src/lib/components/operations/ExpressionConfig.svelte`:
    - [ ] 13.6.1 Column name input for new column
    - [ ] 13.6.2 Expression editor textarea
    - [ ] 13.6.3 Syntax help/examples panel
    - [ ] 13.6.4 Validation feedback
  - [ ] 13.7 Create `frontend/src/lib/components/operations/MLModelConfig.svelte`:
    - [ ] 13.7.1 Model type selector (linear regression, clustering, etc.)
    - [ ] 13.7.2 Feature column multi-select
    - [ ] 13.7.3 Target column selector (for supervised models)
    - [ ] 13.7.4 Hyperparameter inputs based on model type

- [ ] 14.0 Implement Pipeline Builder (Frontend)
  - [ ] 14.1 Create `frontend/src/lib/components/pipeline/StepLibrary.svelte`:
    - [ ] 14.1.1 Categorized list of operations (Filter, Transform, Join, Aggregate, ML)
    - [ ] 14.1.2 Draggable step items
    - [ ] 14.1.3 Tooltips with operation descriptions
  - [ ] 14.2 Create `frontend/src/lib/components/pipeline/StepNode.svelte`:
    - [ ] 14.2.1 Display step type icon and name
    - [ ] 14.2.2 Show brief config summary
    - [ ] 14.2.3 Edit button to open config panel
    - [ ] 14.2.4 Delete button
    - [ ] 14.2.5 Preview button (execute up to this step)
    - [ ] 14.2.6 Connection points for DAG mode
  - [ ] 14.3 Create `frontend/src/lib/components/pipeline/ConnectionLine.svelte`:
    - [ ] 14.3.1 SVG line connecting step nodes
    - [ ] 14.3.2 Handle curved connections
    - [ ] 14.3.3 Highlight on hover
  - [ ] 14.4 Create `frontend/src/lib/components/pipeline/StepConfig.svelte`:
    - [ ] 14.4.1 Dynamic rendering of operation-specific config
    - [ ] 14.4.2 Current schema display
    - [ ] 14.4.3 Output schema preview
    - [ ] 14.4.4 Save and cancel buttons
  - [ ] 14.5 Create `frontend/src/lib/components/pipeline/PipelineCanvas.svelte`:
    - [ ] 14.5.1 Render step nodes in linear or DAG layout
    - [ ] 14.5.2 Drop zone for new steps from library
    - [ ] 14.5.3 Render connection lines between steps
    - [ ] 14.5.4 Click handler to select step and open config
    - [ ] 14.5.5 Support step reordering via drag-and-drop (linear mode)
    - [ ] 14.5.6 Branch creation via right-click menu (DAG mode)

- [ ] 15.0 Implement Analysis Editor Page (Frontend)
  - [ ] 15.1 Create `frontend/src/routes/analysis/[id]/+page.ts`:
    - [ ] 15.1.1 Load analysis data from API
    - [ ] 15.1.2 Load associated data source schemas
    - [ ] 15.1.3 Handle not found error
  - [ ] 15.2 Create `frontend/src/routes/analysis/[id]/+page.svelte`:
    - [ ] 15.2.1 Three-panel layout: StepLibrary | PipelineCanvas | ConfigPanel
    - [ ] 15.2.2 Header with analysis name, save button, run button
    - [ ] 15.2.3 Bottom panel for results/preview data table
    - [ ] 15.2.4 Integrate analysis store for state management
    - [ ] 15.2.5 Integrate compute store for execution status
    - [ ] 15.2.6 Real-time schema updates as pipeline changes
    - [ ] 15.2.7 Autosave on pipeline changes (debounced)
  - [ ] 15.3 Implement execution flow:
    - [ ] 15.3.1 Run button triggers `compute.executeAnalysis()`
    - [ ] 15.3.2 Progress indicator shows current step
    - [ ] 15.3.3 Error display in toast/modal
    - [ ] 15.3.4 Results displayed in DataTable on completion

- [ ] 16.0 Implement Data Source Management Page (Frontend)
  - [ ] 16.1 Create `frontend/src/routes/datasources/+page.svelte`:
    - [ ] 16.1.1 List all data sources with type, name, schema info
    - [ ] 16.1.2 Delete button for each data source
    - [ ] 16.1.3 "Add Data Source" button
    - [ ] 16.1.4 Click to view schema details
  - [ ] 16.2 Create `frontend/src/routes/datasources/new/+page.svelte`:
    - [ ] 16.2.1 Tab selection: File Upload | Database | API
    - [ ] 16.2.2 File upload with drag-and-drop
    - [ ] 16.2.3 Database connection form with test button
    - [ ] 16.2.4 API configuration form with test button
    - [ ] 16.2.5 Schema preview before saving
    - [ ] 16.2.6 Save and redirect to data sources list

- [ ] 17.0 Implement Error Handling & UX Polish
  - [ ] 17.1 Create error boundary component for graceful error display
  - [ ] 17.2 Implement toast notifications for success/error feedback
  - [ ] 17.3 Add loading skeletons for all data-fetching components
  - [ ] 17.4 Implement OOM error handling:
    - [ ] 17.4.1 Backend: Catch subprocess crash and return error status
    - [ ] 17.4.2 Frontend: Display "Analysis ran out of memory" message
    - [ ] 17.4.3 Suggest reducing data size or simplifying pipeline
  - [ ] 17.5 Add confirmation dialogs for destructive actions (delete analysis, delete data source)
  - [ ] 17.6 Implement keyboard shortcuts:
    - [ ] 17.6.1 Ctrl+S to save analysis
    - [ ] 17.6.2 Ctrl+Enter to run analysis
    - [ ] 17.6.3 Delete key to remove selected step

- [ ] 18.0 Testing & Quality Assurance
  - [ ] 18.1 Run all backend tests and ensure they pass
  - [ ] 18.2 Run all frontend tests and ensure they pass
  - [ ] 18.3 Manual testing: Complete happy path flow
    - [ ] 18.3.1 Create new data source (file upload)
    - [ ] 18.3.2 Create new analysis with data source
    - [ ] 18.3.3 Add filter step
    - [ ] 18.3.4 Add select columns step
    - [ ] 18.3.5 Add group by step
    - [ ] 18.3.6 Run analysis
    - [ ] 18.3.7 View results
    - [ ] 18.3.8 Export results to CSV
    - [ ] 18.3.9 Return to gallery and reopen analysis
  - [ ] 18.4 Test error scenarios:
    - [ ] 18.4.1 Invalid file upload (wrong format)
    - [ ] 18.4.2 Invalid pipeline configuration
    - [ ] 18.4.3 Network errors during API calls
  - [ ] 18.5 Performance testing with larger datasets (100K+ rows)

- [ ] 19.0 Documentation & Cleanup
  - [ ] 19.1 Update README.md with project overview and setup instructions
  - [ ] 19.2 Add API documentation comments to backend routes
  - [ ] 19.3 Remove any debug/console.log statements
  - [ ] 19.4 Run linters (`just lint`) and fix any issues
  - [ ] 19.5 Run formatters (`just format`) to ensure consistent code style
  - [ ] 19.6 Create PR with comprehensive description of changes
