# Backend Data Source Module

**Parallel Group**: Backend Modules
**Dependencies**: backend-core
**Blocks**: frontend-api (datasource), integration-testing

## Relevant Files

- `backend/modules/datasource/__init__.py` - Module init
- `backend/modules/datasource/models.py` - SQLAlchemy models
- `backend/modules/datasource/schemas.py` - Pydantic schemas
- `backend/modules/datasource/service.py` - Business logic
- `backend/modules/datasource/routes.py` - API endpoints
- `backend/tests/modules/datasource/test_service.py` - Service tests
- `backend/tests/modules/datasource/test_routes.py` - Route tests

## Tasks

- [ ] 2.0 Implement Data Source Module
  - [ ] 2.1 Create `backend/modules/datasource/models.py`:
    - [ ] 2.1.1 Import Base from core.database
    - [ ] 2.1.2 Define DataSource model with Mapped type hints
    - [ ] 2.1.3 Add id (TEXT PRIMARY KEY)
    - [ ] 2.1.4 Add name (TEXT NOT NULL)
    - [ ] 2.1.5 Add source_type (TEXT NOT NULL) - "file", "database", "api"
    - [ ] 2.1.6 Add config (JSON NOT NULL) - type-specific configuration
    - [ ] 2.1.7 Add schema_cache (JSON NULLABLE) - cached schema info
    - [ ] 2.1.8 Add created_at (TIMESTAMP NOT NULL)
  - [ ] 2.2 Create `backend/modules/datasource/schemas.py`:
    - [ ] 2.2.1 Define ColumnSchema (name, dtype, nullable)
    - [ ] 2.2.2 Define SchemaInfo (columns: list[ColumnSchema], row_count: int | None)
    - [ ] 2.2.3 Define FileDataSourceConfig (file_path, file_type, options)
    - [ ] 2.2.4 Define DatabaseDataSourceConfig (connection_string, query)
    - [ ] 2.2.5 Define APIDataSourceConfig (url, method, headers, auth)
    - [ ] 2.2.6 Define DataSourceCreate (name, source_type, config)
    - [ ] 2.2.7 Define DataSourceResponse (id, name, source_type, config, schema_cache, created_at)
    - [ ] 2.2.8 Define DataSourceListItem (id, name, source_type, created_at, column_count, row_count)
  - [ ] 2.3 Create `backend/modules/datasource/service.py`:
    - [ ] 2.3.1 Implement `create_file_datasource(db, file, name)`:
      - Save uploaded file to UPLOAD_DIR
      - Create DataSource record with file config
      - Extract and cache schema using Polars
      - Return DataSourceResponse
    - [ ] 2.3.2 Implement `create_database_datasource(db, config)`:
      - Validate connection string format
      - Test connection using Polars read_database
      - Create DataSource record
      - Return DataSourceResponse
    - [ ] 2.3.3 Implement `create_api_datasource(db, config)`:
      - Validate API configuration
      - Test API request
      - Create DataSource record
      - Return DataSourceResponse
    - [ ] 2.3.4 Implement `get_datasource(db, id)`:
      - Query DataSource by ID
      - Return DataSourceResponse or raise 404
    - [ ] 2.3.5 Implement `get_datasource_schema(db, id)`:
      - Get DataSource by ID
      - Return cached schema or extract fresh
      - Use Polars to read schema from source
    - [ ] 2.3.6 Implement `list_datasources(db)`:
      - Query all DataSources
      - Return list of DataSourceListItem
    - [ ] 2.3.7 Implement `delete_datasource(db, id)`:
      - Get DataSource by ID
      - Delete associated file if file type
      - Delete database record
      - Return success
    - [ ] 2.3.8 Implement `_extract_schema_from_file(file_path, file_type)`:
      - Use pl.scan_csv/scan_parquet for lazy schema extraction
      - Return SchemaInfo with column details
    - [ ] 2.3.9 Implement `_extract_schema_from_database(connection_string, query)`:
      - Use pl.read_database with limit 0 for schema
      - Return SchemaInfo
  - [ ] 2.4 Create `backend/modules/datasource/routes.py`:
    - [ ] 2.4.1 Create APIRouter with prefix="/datasource" and tag="datasource"
    - [ ] 2.4.2 Implement `POST /upload`:
      - Accept UploadFile and name form field
      - Validate file type (csv, parquet, excel, json)
      - Call create_file_datasource service
      - Return DataSourceResponse
    - [ ] 2.4.3 Implement `POST /connect`:
      - Accept DataSourceCreate body
      - Route to database or API creation based on source_type
      - Return DataSourceResponse
    - [ ] 2.4.4 Implement `GET /`:
      - Call list_datasources service
      - Return list of DataSourceListItem
    - [ ] 2.4.5 Implement `GET /{id}`:
      - Call get_datasource service
      - Return DataSourceResponse
    - [ ] 2.4.6 Implement `GET /{id}/schema`:
      - Call get_datasource_schema service
      - Return SchemaInfo
    - [ ] 2.4.7 Implement `DELETE /{id}`:
      - Call delete_datasource service
      - Return 204 No Content
  - [ ] 2.5 Register router in `backend/api/v1/__init__.py`:
    - [ ] 2.5.1 Import datasource router
    - [ ] 2.5.2 Include router with prefix="/api/v1"
  - [ ] 2.6 Create `backend/modules/datasource/__init__.py`:
    - [ ] 2.6.1 Export router
    - [ ] 2.6.2 Export models
    - [ ] 2.6.3 Export schemas
  - [ ] 2.7 Write tests in `backend/tests/modules/datasource/test_service.py`:
    - [ ] 2.7.1 Test create_file_datasource with CSV
    - [ ] 2.7.2 Test create_file_datasource with Parquet
    - [ ] 2.7.3 Test get_datasource_schema
    - [ ] 2.7.4 Test list_datasources
    - [ ] 2.7.5 Test delete_datasource
  - [ ] 2.8 Write tests in `backend/tests/modules/datasource/test_routes.py`:
    - [ ] 2.8.1 Test POST /upload with valid CSV
    - [ ] 2.8.2 Test POST /upload with invalid file type
    - [ ] 2.8.3 Test GET / returns list
    - [ ] 2.8.4 Test GET /{id}/schema
    - [ ] 2.8.5 Test DELETE /{id}
    - [ ] 2.8.6 Test 404 for non-existent datasource

## Completion Criteria

- [ ] All tests pass (`pytest backend/tests/modules/datasource -v`)
- [ ] Can upload CSV file via API
- [ ] Can retrieve schema from uploaded file
- [ ] Can list all data sources
- [ ] Can delete data source (file removed)
