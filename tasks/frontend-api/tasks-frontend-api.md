# Frontend API Clients

**Parallel Group**: Frontend Core
**Dependencies**: frontend-infrastructure, backend-* (for testing)
**Blocks**: frontend-stores, frontend-gallery, frontend-editor

## Relevant Files

- `frontend/src/lib/api/analysis.ts` - Analysis API functions
- `frontend/src/lib/api/datasource.ts` - Data source API functions
- `frontend/src/lib/api/compute.ts` - Compute API functions
- `frontend/src/lib/api/results.ts` - Results API functions
- `frontend/src/lib/api/client.test.ts` - API client tests

## Tasks

- [ ] 7.0 Implement Frontend API Clients
  - [ ] 7.1 Create `frontend/src/lib/api/analysis.ts`:
    - [ ] 7.1.1 Import types and client utilities
    - [ ] 7.1.2 Implement `createAnalysis(data: CreateAnalysisRequest)`:
      - POST to /analysis
      - Return Analysis
    - [ ] 7.1.3 Implement `listAnalyses()`:
      - GET /analysis
      - Return AnalysisGalleryItem[]
    - [ ] 7.1.4 Implement `getAnalysis(id: string)`:
      - GET /analysis/{id}
      - Return Analysis
    - [ ] 7.1.5 Implement `updateAnalysis(id: string, data: UpdateAnalysisRequest)`:
      - PUT /analysis/{id}
      - Return Analysis
    - [ ] 7.1.6 Implement `deleteAnalysis(id: string)`:
      - DELETE /analysis/{id}
      - Return void
    - [ ] 7.1.7 Implement `linkDataSource(analysisId: string, datasourceId: string)`:
      - POST /analysis/{id}/datasource/{datasourceId}
      - Return void
    - [ ] 7.1.8 Implement `unlinkDataSource(analysisId: string, datasourceId: string)`:
      - DELETE /analysis/{id}/datasource/{datasourceId}
      - Return void
    - [ ] 7.1.9 Export TanStack Query hooks:
      - useAnalyses() - query for list
      - useAnalysis(id) - query for single
      - useCreateAnalysis() - mutation
      - useUpdateAnalysis() - mutation
      - useDeleteAnalysis() - mutation
  - [ ] 7.2 Create `frontend/src/lib/api/datasource.ts`:
    - [ ] 7.2.1 Import types and client utilities
    - [ ] 7.2.2 Implement `uploadFile(file: File, name: string)`:
      - POST to /datasource/upload with FormData
      - Return DataSource
    - [ ] 7.2.3 Implement `connectDatabase(config: DatabaseConfig, name: string)`:
      - POST to /datasource/connect
      - Return DataSource
    - [ ] 7.2.4 Implement `connectAPI(config: APIConfig, name: string)`:
      - POST to /datasource/connect
      - Return DataSource
    - [ ] 7.2.5 Implement `listDataSources()`:
      - GET /datasource
      - Return DataSourceListItem[]
    - [ ] 7.2.6 Implement `getDataSource(id: string)`:
      - GET /datasource/{id}
      - Return DataSource
    - [ ] 7.2.7 Implement `getDataSourceSchema(id: string)`:
      - GET /datasource/{id}/schema
      - Return Schema
    - [ ] 7.2.8 Implement `deleteDataSource(id: string)`:
      - DELETE /datasource/{id}
      - Return void
    - [ ] 7.2.9 Export TanStack Query hooks:
      - useDataSources() - query for list
      - useDataSource(id) - query for single
      - useDataSourceSchema(id) - query for schema
      - useUploadFile() - mutation
      - useConnectDatabase() - mutation
      - useDeleteDataSource() - mutation
  - [ ] 7.3 Create `frontend/src/lib/api/compute.ts`:
    - [ ] 7.3.1 Import types and client utilities
    - [ ] 7.3.2 Implement `executeAnalysis(analysisId: string)`:
      - POST to /analysis/{id}/run
      - Return ComputeResult
    - [ ] 7.3.3 Implement `getComputeStatus(analysisId: string)`:
      - GET /analysis/{id}/status
      - Return ComputeJob
    - [ ] 7.3.4 Implement `previewStep(request: PreviewRequest)`:
      - POST to /compute/preview
      - Return PreviewResponse
    - [ ] 7.3.5 Implement `cancelJob(analysisId: string)`:
      - DELETE /compute/{analysisId}
      - Return void
    - [ ] 7.3.6 Export TanStack Query hooks:
      - useComputeStatus(analysisId) - query with polling
      - useExecuteAnalysis() - mutation
      - usePreviewStep() - mutation
      - useCancelJob() - mutation
  - [ ] 7.4 Create `frontend/src/lib/api/results.ts`:
    - [ ] 7.4.1 Import types and client utilities
    - [ ] 7.4.2 Implement `getResultMetadata(analysisId: string)`:
      - GET /results/{analysisId}
      - Return ResultMetadata
    - [ ] 7.4.3 Implement `getResultData(analysisId: string, request: ResultDataRequest)`:
      - GET /results/{analysisId}/data with query params
      - Return ResultDataResponse
    - [ ] 7.4.4 Implement `exportResult(analysisId: string, format: ExportFormat)`:
      - POST /results/{analysisId}/export
      - Return ExportResponse
    - [ ] 7.4.5 Implement `getDownloadUrl(analysisId: string, filename: string)`:
      - Return full download URL
    - [ ] 7.4.6 Export TanStack Query hooks:
      - useResultMetadata(analysisId) - query
      - useResultData(analysisId, request) - query with pagination
      - useExportResult() - mutation
  - [ ] 7.5 Create `frontend/src/lib/api/index.ts`:
    - [ ] 7.5.1 Re-export all API functions
    - [ ] 7.5.2 Re-export all hooks
  - [ ] 7.6 Write tests in `frontend/src/lib/api/client.test.ts`:
    - [ ] 7.6.1 Test fetchAPI handles successful response
    - [ ] 7.6.2 Test fetchAPI throws APIError on 4xx
    - [ ] 7.6.3 Test fetchAPI throws APIError on 5xx
    - [ ] 7.6.4 Test uploadFile sends FormData correctly
    - [ ] 7.6.5 Test get/post/put/del helpers

## Completion Criteria

- [ ] All tests pass (`npm run test`)
- [ ] TypeScript compiles without errors
- [ ] Can make API calls to backend (when running)
- [ ] TanStack Query hooks properly typed
- [ ] Error handling works correctly
