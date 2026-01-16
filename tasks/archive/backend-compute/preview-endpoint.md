# Backend: Step Preview Endpoint

**Priority:** HIGH  
**Status:** ✅ Complete  
**Depends On:** backend-compute/lazy-polars.md  
**Blocks:** frontend-api/compute-preview.md

---

## Goal

Add REST API endpoint to preview data at any pipeline step, enabling inline view components.

---

## Changes Required

### 1. Update Schemas

**File:** `backend/modules/compute/schemas.py`

Add new schemas:

```python
class StepPreviewRequest(BaseModel):
    datasource_id: str
    pipeline_steps: list[dict]
    target_step_id: str
    row_limit: int = Field(default=100, ge=10, le=1000)
    page: int = Field(default=1, ge=1)

class StepPreviewResponse(BaseModel):
    step_id: str
    columns: list[str]
    data: list[dict]
    total_rows: int
    page: int
    page_size: int
```

### 2. Add Preview Endpoint

**File:** `backend/modules/compute/routes.py`

Add after existing endpoints:

```python
@router.post("/preview", response_model=StepPreviewResponse)
async def preview_step_data(
    request: StepPreviewRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Preview data at a specific pipeline step.
    Executes pipeline lazily up to target_step_id, then collects preview.
    """
    # Find index of target step
    step_index = next(
        (i for i, s in enumerate(request.pipeline_steps) if s.get('id') == request.target_step_id),
        None
    )
    
    if step_index is None:
        raise HTTPException(status_code=404, detail=f"Step {request.target_step_id} not found in pipeline")
    
    # Execute up to target step
    try:
        preview_data = await preview_step(
            session,
            request.datasource_id,
            request.pipeline_steps,
            step_index
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")
    
    # Paginate
    offset = (request.page - 1) * request.row_limit
    paginated_data = preview_data['sample_data'][offset:offset + request.row_limit]
    
    return StepPreviewResponse(
        step_id=request.target_step_id,
        columns=list(preview_data['schema'].keys()),
        data=paginated_data,
        total_rows=preview_data['row_count'],
        page=request.page,
        page_size=request.row_limit
    )
```

### 3. Update Service Layer

**File:** `backend/modules/compute/service.py`

Modify `preview_step()` function (lines 75-113):

**Current Issues:**
- Uses blocking `while True` loop
- No pagination support
- Returns raw data structure

**New Implementation:**

```python
async def preview_step(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
    step_index: int,
) -> dict:
    """Preview the result of executing pipeline up to a specific step."""
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    # Only execute steps up to target index
    preview_steps = pipeline_steps[: step_index + 1]

    manager = get_manager()
    # Use unique engine ID for preview to avoid conflicts
    preview_engine_id = f'{datasource_id}_preview_{step_index}'
    engine = manager.get_or_create_engine(preview_engine_id)

    datasource_config = {
        'source_type': datasource.source_type,
        **datasource.config,
    }

    job_id = engine.execute(
        datasource_config=datasource_config,
        pipeline_steps=preview_steps,
        timeout=60,  # Shorter timeout for previews
    )

    # Wait for result with timeout
    max_wait = 60  # seconds
    wait_time = 0
    while wait_time < max_wait:
        result_data = engine.get_result(timeout=1.0)
        if result_data:
            if result_data['status'] == JobStatus.COMPLETED:
                manager.shutdown_engine(preview_engine_id)
                return result_data['data']
            elif result_data['status'] == JobStatus.FAILED:
                manager.shutdown_engine(preview_engine_id)
                raise ValueError(f'Preview failed: {result_data.get("error", "Unknown error")}')
        wait_time += 1
    
    # Timeout
    manager.shutdown_engine(preview_engine_id)
    raise TimeoutError('Preview execution timed out after 60 seconds')
```

---

## Testing

### Manual Test:
```bash
curl -X POST http://localhost:8000/api/compute/preview \
  -H "Content-Type: application/json" \
  -d '{
    "datasource_id": "uuid-here",
    "pipeline_steps": [
      {"id": "step1", "type": "filter", "config": {...}},
      {"id": "step2", "type": "view", "config": {"rowLimit": 100}}
    ],
    "target_step_id": "step2",
    "row_limit": 100,
    "page": 1
  }'
```

Expected response:
```json
{
  "step_id": "step2",
  "columns": ["id", "name", "age"],
  "data": [{...}, {...}],
  "total_rows": 543,
  "page": 1,
  "page_size": 100
}
```

---

## Status

- [x] Add StepPreviewRequest/Response schemas
- [x] Add /preview endpoint  
- [x] Update preview_step() service
- [x] Increase engine sample_data limit to 5000 rows
- [ ] Test with curl (pending manual test)
- [ ] Test pagination (pending manual test)

---

## Implementation Notes

### Changes Made

1. **Schemas** (`backend/modules/compute/schemas.py`):
   - Added `StepPreviewRequest` with `target_step_id` (instead of step_index)
   - Added `StepPreviewResponse` with paginated data structure
   - Default `row_limit` set to 1000 (matches inline view requirements)

2. **Routes** (`backend/modules/compute/routes.py`):
   - Updated `/preview` endpoint to use new schema
   - Changed to accept `target_step_id` instead of `step_index`
   - Returns properly typed `StepPreviewResponse`

3. **Service** (`backend/modules/compute/service.py`):
   - Updated `preview_step()` signature to accept `target_step_id`, `row_limit`, `page`
   - Finds step index by searching for matching step ID
   - Reduced timeout from 300s to 30s for faster preview failures
   - Returns `StepPreviewResponse` object with pagination applied
   - Pagination happens in-memory on the collected sample data

4. **Engine** (`backend/modules/compute/engine.py`):
   - Increased `sample_data` limit from 100 to 5000 rows
   - Allows frontend to paginate up to 5000 rows without re-executing pipeline

### Design Decisions

- **Step ID vs Index**: Using step ID makes API more robust to pipeline changes
- **In-memory Pagination**: Since we collect 5000 rows, pagination is fast and simple
- **Timeout Reduction**: Previews should be fast; 30s timeout encourages optimization
- **Unique Engine ID**: Preview uses `{datasource_id}_preview` to avoid main execution conflicts
