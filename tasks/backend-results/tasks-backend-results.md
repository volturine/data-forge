# Backend Results Module

**Parallel Group**: Backend Modules
**Dependencies**: backend-core, backend-compute
**Blocks**: integration-testing

## Relevant Files

- `backend/modules/results/__init__.py` - Module init
- `backend/modules/results/schemas.py` - Pydantic schemas
- `backend/modules/results/service.py` - Business logic
- `backend/modules/results/routes.py` - API endpoints
- `backend/tests/modules/results/test_routes.py` - Route tests

## Tasks

- [ ] 5.0 Implement Results Module
  - [ ] 5.1 Create `backend/modules/results/schemas.py`:
    - [ ] 5.1.1 Define ResultMetadata:
      - analysis_id: str
      - row_count: int
      - column_count: int
      - columns: list[ColumnSchema]
      - file_size_bytes: int
      - created_at: datetime
    - [ ] 5.1.2 Define ResultDataRequest:
      - offset: int = 0
      - limit: int = 100
      - sort_by: str | None = None
      - sort_desc: bool = False
    - [ ] 5.1.3 Define ResultDataResponse:
      - columns: list[str]
      - data: list[dict]
      - total_rows: int
      - offset: int
      - limit: int
    - [ ] 5.1.4 Define ExportRequest:
      - format: str (csv, parquet, excel, json)
    - [ ] 5.1.5 Define ExportResponse:
      - download_url: str
      - filename: str
      - file_size_bytes: int
  - [ ] 5.2 Create `backend/modules/results/service.py`:
    - [ ] 5.2.1 Implement `store_result(analysis_id, df)`:
      - Generate result filename: {analysis_id}.parquet
      - Get results directory from config
      - Save DataFrame to parquet
      - Return result_path
    - [ ] 5.2.2 Implement `get_result_metadata(analysis_id)`:
      - Get analysis from database
      - Check result_path exists
      - Read parquet metadata (schema, row count)
      - Get file size
      - Return ResultMetadata
    - [ ] 5.2.3 Implement `get_result_data(analysis_id, request: ResultDataRequest)`:
      - Get analysis from database
      - Load result parquet with LazyFrame
      - Apply offset and limit
      - Apply sorting if specified
      - Collect and convert to list of dicts
      - Return ResultDataResponse
    - [ ] 5.2.4 Implement `export_result(analysis_id, format: str)`:
      - Get analysis from database
      - Load result parquet
      - Export to requested format:
        - csv: df.write_csv()
        - parquet: copy existing file
        - excel: df.write_excel()
        - json: df.write_json()
      - Generate download filename
      - Return ExportResponse with URL
    - [ ] 5.2.5 Implement `delete_result(analysis_id)`:
      - Get result_path from analysis
      - Delete parquet file if exists
      - Return success
    - [ ] 5.2.6 Implement `get_result_file_path(analysis_id)`:
      - Get analysis from database
      - Return full file path for streaming
  - [ ] 5.3 Create `backend/modules/results/routes.py`:
    - [ ] 5.3.1 Create APIRouter with prefix="/results" and tag="results"
    - [ ] 5.3.2 Implement `GET /{analysis_id}`:
      - Call get_result_metadata service
      - Return ResultMetadata
    - [ ] 5.3.3 Implement `GET /{analysis_id}/data`:
      - Accept ResultDataRequest query params
      - Call get_result_data service
      - Return ResultDataResponse
    - [ ] 5.3.4 Implement `POST /{analysis_id}/export`:
      - Accept ExportRequest body
      - Call export_result service
      - Return ExportResponse
    - [ ] 5.3.5 Implement `GET /{analysis_id}/download/{filename}`:
      - Stream file response for download
      - Set appropriate content-type header
      - Support range requests for large files
  - [ ] 5.4 Register router in `backend/api/v1/__init__.py`
  - [ ] 5.5 Create `backend/modules/results/__init__.py`:
    - [ ] 5.5.1 Export router
    - [ ] 5.5.2 Export schemas
    - [ ] 5.5.3 Export service functions
  - [ ] 5.6 Write tests in `backend/tests/modules/results/test_routes.py`:
    - [ ] 5.6.1 Test GET /{analysis_id} returns metadata
    - [ ] 5.6.2 Test GET /{analysis_id}/data returns paginated data
    - [ ] 5.6.3 Test GET /{analysis_id}/data with offset
    - [ ] 5.6.4 Test GET /{analysis_id}/data with sorting
    - [ ] 5.6.5 Test POST /{analysis_id}/export to CSV
    - [ ] 5.6.6 Test POST /{analysis_id}/export to Parquet
    - [ ] 5.6.7 Test 404 for analysis without results

## Completion Criteria

- [ ] All tests pass (`pytest backend/tests/modules/results -v`)
- [ ] Can retrieve result metadata (row count, schema)
- [ ] Can retrieve paginated result data
- [ ] Can sort result data
- [ ] Can export to CSV, Parquet, Excel, JSON
- [ ] Large file downloads stream properly
