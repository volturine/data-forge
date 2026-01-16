# Frontend Infrastructure

**Parallel Group**: Frontend Foundation
**Dependencies**: None (can start with backend)
**Blocks**: All other frontend modules

## Relevant Files

- `frontend/src/lib/types/analysis.ts` - Analysis type definitions
- `frontend/src/lib/types/datasource.ts` - Data source type definitions
- `frontend/src/lib/types/compute.ts` - Compute type definitions
- `frontend/src/lib/types/schema.ts` - Schema type definitions
- `frontend/src/lib/api/client.ts` - Base API client
- `frontend/src/routes/+layout.svelte` - Root layout with providers
- `frontend/package.json` - Dependencies

## Tasks

- [x] 6.0 Setup Frontend Infrastructure
  - [x] 6.1 Install required dependencies:
    - [x] 6.1.1 Run `npm install @tanstack/svelte-query`
    - [x] 6.1.2 Run `npm install -D @types/node` (if not present)
  - [x] 6.2 Create `frontend/src/lib/types/schema.ts`:
    - [x] 6.2.1 Define PolarsDataType enum/type matching Polars dtypes
    - [x] 6.2.2 Define Column interface (name, dtype, nullable)
    - [x] 6.2.3 Define Schema interface (columns: Column[], rowCount?: number)
  - [x] 6.3 Create `frontend/src/lib/types/datasource.ts`:
    - [x] 6.3.1 Define DataSourceType enum ('file' | 'database' | 'api')
    - [x] 6.3.2 Define FileConfig interface (filePath, fileType, options)
    - [x] 6.3.3 Define DatabaseConfig interface (connectionString, query)
    - [x] 6.3.4 Define APIConfig interface (url, method, headers, auth)
    - [x] 6.3.5 Define DataSource interface (id, name, sourceType, config, schemaCache, createdAt)
    - [x] 6.3.6 Define DataSourceListItem interface (id, name, sourceType, createdAt, columnCount, rowCount)
    - [x] 6.3.7 Define CreateDataSourceRequest interface
  - [x] 6.4 Create `frontend/src/lib/types/analysis.ts`:
    - [x] 6.4.1 Define PipelineStepType enum (filter, select, join, groupBy, sort, expression, window, mlModel)
    - [x] 6.4.2 Define PipelineStep interface (id, type, config, dependsOn)
    - [x] 6.4.3 Define FilterConfig interface (conditions, logic)
    - [x] 6.4.4 Define SelectConfig interface (columns, renames)
    - [x] 6.4.5 Define JoinConfig interface (rightDatasetId, joinType, leftOn, rightOn, suffix)
    - [x] 6.4.6 Define GroupByConfig interface (groupBy, aggregations)
    - [x] 6.4.7 Define SortConfig interface (columns, descending)
    - [x] 6.4.8 Define ExpressionConfig interface (columnName, expression)
    - [x] 6.4.9 Define AnalysisStatus enum (draft, running, completed, error)
    - [x] 6.4.10 Define Analysis interface (full analysis object)
    - [x] 6.4.11 Define AnalysisGalleryItem interface (for gallery view)
    - [x] 6.4.12 Define CreateAnalysisRequest interface
    - [x] 6.4.13 Define UpdateAnalysisRequest interface
  - [x] 6.5 Create `frontend/src/lib/types/compute.ts`:
    - [x] 6.5.1 Define ComputeStatus enum (queued, running, completed, error, cancelled)
    - [x] 6.5.2 Define ComputeJob interface (jobId, status, progress, currentStep, errorMessage)
    - [x] 6.5.3 Define ExecuteRequest interface (analysisId, executeMode, stepId)
    - [x] 6.5.4 Define PreviewRequest interface (analysisId, stepId, limit)
    - [x] 6.5.5 Define PreviewResponse interface (columns, data, rowCount)
    - [x] 6.5.6 Define ComputeResult interface (jobId, status, resultPath, rowCount, columnCount)
  - [ ] 6.6 Create `frontend/src/lib/types/results.ts`:
    - [ ] 6.6.1 Define ResultMetadata interface
    - [ ] 6.6.2 Define ResultDataRequest interface (offset, limit, sortBy, sortDesc)
    - [ ] 6.6.3 Define ResultDataResponse interface (columns, data, totalRows, offset, limit)
    - [ ] 6.6.4 Define ExportFormat enum (csv, parquet, excel, json)
    - [ ] 6.6.5 Define ExportResponse interface (downloadUrl, filename, fileSizeBytes)
  - [ ] 6.7 Create `frontend/src/lib/types/index.ts`:
    - [ ] 6.7.1 Re-export all types from sub-modules
  - [x] 6.8 Create `frontend/src/lib/api/client.ts`:
    - [x] 6.8.1 Define APIError class with status, message, details
    - [x] 6.8.2 Define base URL constant (import.meta.env.VITE_API_URL or '/api/v1')
    - [x] 6.8.3 Implement `fetchAPI<T>(endpoint, options)`:
      - Build full URL
      - Set default headers (Content-Type: application/json)
      - Make fetch request
      - Handle non-ok responses (throw APIError)
      - Parse and return JSON
    - [x] 6.8.4 Implement `get<T>(endpoint)` helper
    - [x] 6.8.5 Implement `post<T>(endpoint, data)` helper
    - [x] 6.8.6 Implement `put<T>(endpoint, data)` helper
    - [x] 6.8.7 Implement `del(endpoint)` helper (DELETE)
    - [x] 6.8.8 Implement `uploadFile<T>(endpoint, file, additionalData)` helper
  - [x] 6.9 Setup TanStack Query in `frontend/src/routes/+layout.svelte`:
    - [x] 6.9.1 Import QueryClient and QueryClientProvider
    - [x] 6.9.2 Create QueryClient instance with default options
    - [x] 6.9.3 Wrap slot with QueryClientProvider
  - [ ] 6.10 Create `frontend/src/lib/api/index.ts`:
    - [ ] 6.10.1 Export client utilities
    - [ ] 6.10.2 Export APIError class

## Completion Criteria

- [x] All dependencies installed (`npm install` succeeds)
- [x] TypeScript compiles without errors (`npm run check`)
- [ ] Types are properly exported and importable (needs index.ts)
- [x] API client can make requests (test with health endpoint)
- [x] TanStack Query provider wraps the app
