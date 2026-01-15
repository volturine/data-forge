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

- [ ] 6.0 Setup Frontend Infrastructure
  - [ ] 6.1 Install required dependencies:
    - [ ] 6.1.1 Run `npm install @tanstack/svelte-query`
    - [ ] 6.1.2 Run `npm install -D @types/node` (if not present)
  - [ ] 6.2 Create `frontend/src/lib/types/schema.ts`:
    - [ ] 6.2.1 Define PolarsDataType enum/type matching Polars dtypes
    - [ ] 6.2.2 Define Column interface (name, dtype, nullable)
    - [ ] 6.2.3 Define Schema interface (columns: Column[], rowCount?: number)
  - [ ] 6.3 Create `frontend/src/lib/types/datasource.ts`:
    - [ ] 6.3.1 Define DataSourceType enum ('file' | 'database' | 'api')
    - [ ] 6.3.2 Define FileConfig interface (filePath, fileType, options)
    - [ ] 6.3.3 Define DatabaseConfig interface (connectionString, query)
    - [ ] 6.3.4 Define APIConfig interface (url, method, headers, auth)
    - [ ] 6.3.5 Define DataSource interface (id, name, sourceType, config, schemaCache, createdAt)
    - [ ] 6.3.6 Define DataSourceListItem interface (id, name, sourceType, createdAt, columnCount, rowCount)
    - [ ] 6.3.7 Define CreateDataSourceRequest interface
  - [ ] 6.4 Create `frontend/src/lib/types/analysis.ts`:
    - [ ] 6.4.1 Define PipelineStepType enum (filter, select, join, groupBy, sort, expression, window, mlModel)
    - [ ] 6.4.2 Define PipelineStep interface (id, type, config, dependsOn)
    - [ ] 6.4.3 Define FilterConfig interface (conditions, logic)
    - [ ] 6.4.4 Define SelectConfig interface (columns, renames)
    - [ ] 6.4.5 Define JoinConfig interface (rightDatasetId, joinType, leftOn, rightOn, suffix)
    - [ ] 6.4.6 Define GroupByConfig interface (groupBy, aggregations)
    - [ ] 6.4.7 Define SortConfig interface (columns, descending)
    - [ ] 6.4.8 Define ExpressionConfig interface (columnName, expression)
    - [ ] 6.4.9 Define AnalysisStatus enum (draft, running, completed, error)
    - [ ] 6.4.10 Define Analysis interface (full analysis object)
    - [ ] 6.4.11 Define AnalysisGalleryItem interface (for gallery view)
    - [ ] 6.4.12 Define CreateAnalysisRequest interface
    - [ ] 6.4.13 Define UpdateAnalysisRequest interface
  - [ ] 6.5 Create `frontend/src/lib/types/compute.ts`:
    - [ ] 6.5.1 Define ComputeStatus enum (queued, running, completed, error, cancelled)
    - [ ] 6.5.2 Define ComputeJob interface (jobId, status, progress, currentStep, errorMessage)
    - [ ] 6.5.3 Define ExecuteRequest interface (analysisId, executeMode, stepId)
    - [ ] 6.5.4 Define PreviewRequest interface (analysisId, stepId, limit)
    - [ ] 6.5.5 Define PreviewResponse interface (columns, data, rowCount)
    - [ ] 6.5.6 Define ComputeResult interface (jobId, status, resultPath, rowCount, columnCount)
  - [ ] 6.6 Create `frontend/src/lib/types/results.ts`:
    - [ ] 6.6.1 Define ResultMetadata interface
    - [ ] 6.6.2 Define ResultDataRequest interface (offset, limit, sortBy, sortDesc)
    - [ ] 6.6.3 Define ResultDataResponse interface (columns, data, totalRows, offset, limit)
    - [ ] 6.6.4 Define ExportFormat enum (csv, parquet, excel, json)
    - [ ] 6.6.5 Define ExportResponse interface (downloadUrl, filename, fileSizeBytes)
  - [ ] 6.7 Create `frontend/src/lib/types/index.ts`:
    - [ ] 6.7.1 Re-export all types from sub-modules
  - [ ] 6.8 Create `frontend/src/lib/api/client.ts`:
    - [ ] 6.8.1 Define APIError class with status, message, details
    - [ ] 6.8.2 Define base URL constant (import.meta.env.VITE_API_URL or '/api/v1')
    - [ ] 6.8.3 Implement `fetchAPI<T>(endpoint, options)`:
      - Build full URL
      - Set default headers (Content-Type: application/json)
      - Make fetch request
      - Handle non-ok responses (throw APIError)
      - Parse and return JSON
    - [ ] 6.8.4 Implement `get<T>(endpoint)` helper
    - [ ] 6.8.5 Implement `post<T>(endpoint, data)` helper
    - [ ] 6.8.6 Implement `put<T>(endpoint, data)` helper
    - [ ] 6.8.7 Implement `del(endpoint)` helper (DELETE)
    - [ ] 6.8.8 Implement `uploadFile<T>(endpoint, file, additionalData)` helper
  - [ ] 6.9 Setup TanStack Query in `frontend/src/routes/+layout.svelte`:
    - [ ] 6.9.1 Import QueryClient and QueryClientProvider
    - [ ] 6.9.2 Create QueryClient instance with default options
    - [ ] 6.9.3 Wrap slot with QueryClientProvider
  - [ ] 6.10 Create `frontend/src/lib/api/index.ts`:
    - [ ] 6.10.1 Export client utilities
    - [ ] 6.10.2 Export APIError class

## Completion Criteria

- [ ] All dependencies installed (`npm install` succeeds)
- [ ] TypeScript compiles without errors (`npm run check`)
- [ ] Types are properly exported and importable
- [ ] API client can make requests (test with health endpoint)
- [ ] TanStack Query provider wraps the app
