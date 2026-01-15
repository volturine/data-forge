# Backend Analysis Module

**Parallel Group**: Backend Modules
**Dependencies**: backend-core, backend-datasource (for linking)
**Blocks**: backend-compute, frontend-api (analysis), integration-testing

## Relevant Files

- `backend/modules/analysis/__init__.py` - Module init
- `backend/modules/analysis/models.py` - SQLAlchemy models
- `backend/modules/analysis/schemas.py` - Pydantic schemas
- `backend/modules/analysis/service.py` - Business logic
- `backend/modules/analysis/routes.py` - API endpoints
- `backend/tests/modules/analysis/test_service.py` - Service tests
- `backend/tests/modules/analysis/test_routes.py` - Route tests

## Tasks

- [ ] 3.0 Implement Analysis Module
  - [ ] 3.1 Create `backend/modules/analysis/models.py`:
    - [ ] 3.1.1 Import Base from core.database
    - [ ] 3.1.2 Define Analysis model:
      - id: Mapped[str] PRIMARY KEY
      - name: Mapped[str] NOT NULL
      - description: Mapped[str | None]
      - pipeline_definition: Mapped[dict] JSON NOT NULL
      - status: Mapped[str] NOT NULL (draft, running, completed, error)
      - created_at: Mapped[datetime] NOT NULL
      - updated_at: Mapped[datetime] NOT NULL
      - result_path: Mapped[str | None]
      - thumbnail: Mapped[str | None]
    - [ ] 3.1.3 Define AnalysisDataSource model:
      - analysis_id: Mapped[str] FK PRIMARY KEY
      - datasource_id: Mapped[str] FK PRIMARY KEY
    - [ ] 3.1.4 Add relationships between models
  - [ ] 3.2 Create `backend/modules/analysis/schemas.py`:
    - [ ] 3.2.1 Define PipelineStepConfig (base for step configs)
    - [ ] 3.2.2 Define PipelineStep (id, type, config, depends_on)
    - [ ] 3.2.3 Define AnalysisCreate (name, description, datasource_ids, pipeline_steps)
    - [ ] 3.2.4 Define AnalysisUpdate (name, description, pipeline_steps)
    - [ ] 3.2.5 Define AnalysisResponse (full analysis with all fields)
    - [ ] 3.2.6 Define AnalysisGalleryItem (id, name, thumbnail, created_at, updated_at, row_count, column_count, status)
    - [ ] 3.2.7 Define AnalysisList (items: list[AnalysisGalleryItem])
  - [ ] 3.3 Create `backend/modules/analysis/service.py`:
    - [ ] 3.3.1 Implement `create_analysis(db, data: AnalysisCreate)`:
      - Generate UUID for id
      - Create Analysis record with status="draft"
      - Create AnalysisDataSource links
      - Return AnalysisResponse
    - [ ] 3.3.2 Implement `get_analysis(db, id: str)`:
      - Query Analysis by ID with datasource links
      - Return AnalysisResponse or raise 404
    - [ ] 3.3.3 Implement `list_analyses(db)`:
      - Query all analyses ordered by updated_at desc
      - Return list of AnalysisGalleryItem
    - [ ] 3.3.4 Implement `update_analysis(db, id: str, data: AnalysisUpdate)`:
      - Get existing analysis
      - Update fields (name, description, pipeline_steps)
      - Update updated_at timestamp
      - Return AnalysisResponse
    - [ ] 3.3.5 Implement `delete_analysis(db, id: str)`:
      - Get existing analysis
      - Delete result files if exist
      - Delete AnalysisDataSource links (cascade)
      - Delete Analysis record
      - Return success
    - [ ] 3.3.6 Implement `link_datasource(db, analysis_id: str, datasource_id: str)`:
      - Create AnalysisDataSource record
      - Return success
    - [ ] 3.3.7 Implement `unlink_datasource(db, analysis_id: str, datasource_id: str)`:
      - Delete AnalysisDataSource record
      - Return success
    - [ ] 3.3.8 Implement `update_analysis_status(db, id: str, status: str)`:
      - Update status field
      - Return success
    - [ ] 3.3.9 Implement `update_analysis_result(db, id: str, result_path: str, thumbnail: str | None)`:
      - Update result_path and thumbnail
      - Return success
  - [ ] 3.4 Create `backend/modules/analysis/routes.py`:
    - [ ] 3.4.1 Create APIRouter with prefix="/analysis" and tag="analysis"
    - [ ] 3.4.2 Implement `POST /`:
      - Accept AnalysisCreate body
      - Call create_analysis service
      - Return AnalysisResponse with 201 status
    - [ ] 3.4.3 Implement `GET /`:
      - Call list_analyses service
      - Return list of AnalysisGalleryItem
    - [ ] 3.4.4 Implement `GET /{id}`:
      - Call get_analysis service
      - Return AnalysisResponse
    - [ ] 3.4.5 Implement `PUT /{id}`:
      - Accept AnalysisUpdate body
      - Call update_analysis service
      - Return AnalysisResponse
    - [ ] 3.4.6 Implement `DELETE /{id}`:
      - Call delete_analysis service
      - Return 204 No Content
    - [ ] 3.4.7 Implement `POST /{id}/datasource/{datasource_id}`:
      - Call link_datasource service
      - Return 201 Created
    - [ ] 3.4.8 Implement `DELETE /{id}/datasource/{datasource_id}`:
      - Call unlink_datasource service
      - Return 204 No Content
  - [ ] 3.5 Register router in `backend/api/v1/__init__.py`:
    - [ ] 3.5.1 Import analysis router
    - [ ] 3.5.2 Include router with prefix="/api/v1"
  - [ ] 3.6 Create `backend/modules/analysis/__init__.py`:
    - [ ] 3.6.1 Export router
    - [ ] 3.6.2 Export models
    - [ ] 3.6.3 Export schemas
  - [ ] 3.7 Write tests in `backend/tests/modules/analysis/test_service.py`:
    - [ ] 3.7.1 Test create_analysis
    - [ ] 3.7.2 Test get_analysis
    - [ ] 3.7.3 Test list_analyses
    - [ ] 3.7.4 Test update_analysis
    - [ ] 3.7.5 Test delete_analysis
    - [ ] 3.7.6 Test link/unlink datasource
  - [ ] 3.8 Write tests in `backend/tests/modules/analysis/test_routes.py`:
    - [ ] 3.8.1 Test POST / creates analysis
    - [ ] 3.8.2 Test GET / returns list
    - [ ] 3.8.3 Test GET /{id} returns analysis
    - [ ] 3.8.4 Test PUT /{id} updates analysis
    - [ ] 3.8.5 Test DELETE /{id} removes analysis
    - [ ] 3.8.6 Test 404 for non-existent analysis

## Completion Criteria

- [ ] All tests pass (`pytest backend/tests/modules/analysis -v`)
- [ ] Can create analysis with pipeline steps
- [ ] Can update analysis pipeline
- [ ] Can list analyses for gallery
- [ ] Can delete analysis
- [ ] Can link/unlink data sources
