import contextlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import AnalysisId, DataSourceId, parse_analysis_id, parse_datasource_id
from modules.analysis import schemas, service
from modules.analysis.step_schemas import StepType, get_config_model, get_step_catalog
from modules.compute import service as compute_service
from modules.locks import service as lock_service
from modules.mcp.decorators import deterministic_tool

router = APIRouter(prefix='/analysis', tags=['analysis'])


@router.post('/validate')
@handle_errors(operation='validate analysis', value_error_status=400)
@deterministic_tool
def validate_analysis(
    data: schemas.AnalysisCreateSchema,
    session: Session = Depends(get_db),
):
    """Validate analysis payload without persisting."""
    return service.validate_analysis(session, data)


@router.post('', response_model=schemas.AnalysisResponseSchema)
@handle_errors(operation='create analysis', value_error_status=400)
@deterministic_tool
def create_analysis(
    data: schemas.AnalysisCreateSchema,
    session: Session = Depends(get_db),
):
    """Create a new analysis pipeline.

    IMPORTANT: Before calling this, use GET /api/v1/datasource to list existing datasources
    and obtain a valid datasource ID. Both `tabs[].datasource.id` and
    `tabs[].output.output_datasource_id` must reference an existing datasource ID
    (or a sibling tab's output_datasource_id). Do NOT invent datasource IDs.

    Each tab requires: a datasource (with id and config.branch), an output
    (with output_datasource_id, format, filename), and optionally steps.
    Use GET /api/v1/analysis/step-types to discover valid step types and their config schemas.
    """
    return service.create_analysis(session, data)


@router.get('', response_model=list[schemas.AnalysisGalleryItemSchema])
@handle_errors(operation='list analyses')
@deterministic_tool
def list_analyses(session: Session = Depends(get_db)):
    """List all analyses as gallery items with id, name, thumbnail, and timestamps."""
    return service.list_analyses(session)


@router.get('/step-types')
@handle_errors(operation='list step types')
@deterministic_tool
def list_step_types():
    """List all available pipeline step types with descriptions and config schemas.

    Use this to discover what operations are available and what configuration
    each requires before adding steps to an analysis.
    """
    return get_step_catalog()


@router.get('/{analysis_id}', response_model=schemas.AnalysisResponseSchema)
@handle_errors(operation='get analysis', value_error_status=404)
@deterministic_tool
def get_analysis(
    analysis_id: AnalysisId,
    response: Response,
    session: Session = Depends(get_db),
):
    """Get a single analysis by ID with full pipeline definition including all tabs and steps."""
    analysis = service.get_analysis(session, parse_analysis_id(analysis_id))
    response.headers['ETag'] = f'"analysis-{analysis.id}-{analysis.updated_at.isoformat()}"'
    response.headers['X-Analysis-Version'] = analysis.updated_at.isoformat()
    return analysis


@router.put('/{analysis_id}', response_model=schemas.AnalysisResponseSchema)
@handle_errors(operation='update analysis', value_error_status=409)
@deterministic_tool
def update_analysis(
    analysis_id: AnalysisId,
    data: schemas.AnalysisUpdateSchema,
    session: Session = Depends(get_db),
):
    """Update an analysis.

    Requires client_id and lock_token from the lock system. Replaces the full tabs array.
    Use step-level endpoints for adding/removing individual steps.
    """
    analysis_id_value = parse_analysis_id(analysis_id)
    try:
        service.get_analysis(session, analysis_id_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not data.client_id or not data.lock_token:
        raise HTTPException(status_code=409, detail='Editing lock required')

    lock_service.validate_lock(session, analysis_id_value, data.client_id, data.lock_token)

    return service.update_analysis(session, analysis_id_value, data)


@router.delete('/{analysis_id}', status_code=204)
@handle_errors(operation='delete analysis', value_error_status=404)
@deterministic_tool
def delete_analysis(
    analysis_id: AnalysisId,
    session: Session = Depends(get_db),
):
    """Delete an analysis and its associated data."""
    analysis_id_value = parse_analysis_id(analysis_id)
    try:
        service.delete_analysis(session, analysis_id_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return None


@router.post('/{analysis_id}/datasource/{datasource_id}')
@handle_errors(operation='link datasource', value_error_status=400)
@deterministic_tool
def link_datasource(
    analysis_id: AnalysisId,
    datasource_id: DataSourceId,
    session: Session = Depends(get_db),
):
    """Link a datasource to an analysis, creating a new tab if needed."""
    analysis_id_value = parse_analysis_id(analysis_id)
    datasource_id_value = parse_datasource_id(datasource_id)
    service.link_datasource(session, analysis_id_value, datasource_id_value)
    return {'message': f'DataSource {datasource_id_value} linked to Analysis {analysis_id_value}'}


@router.post('/{analysis_id}/execute')
@handle_errors(operation='execute analysis', value_error_status=400)
@deterministic_tool
async def execute_analysis(
    analysis_id: AnalysisId,
    request: Request,
    session: Session = Depends(get_db),
):
    """Execute the analysis pipeline and return preview results with schema, rows, and row count."""
    analysis_payload = None
    body = None
    with contextlib.suppress(ValueError):
        body = await request.json()
    if isinstance(body, dict):
        analysis_payload = body.get('pipeline')

    analysis_id_value = parse_analysis_id(analysis_id)

    if not isinstance(analysis_payload, dict):
        raise HTTPException(status_code=400, detail='pipeline payload must be provided')

    tabs = analysis_payload.get('tabs', [])
    if not isinstance(tabs, list):
        raise HTTPException(status_code=400, detail='pipeline tabs must be a list')
    selected = next((tab for tab in tabs if tab.get('steps')), None)
    if not selected:
        raise HTTPException(status_code=400, detail='pipeline payload missing tab steps')
    datasource = selected.get('datasource')
    if not isinstance(datasource, dict):
        raise HTTPException(status_code=400, detail='Analysis tab datasource must be a dict')
    datasource_id = datasource.get('id')
    steps = selected.get('steps', [])
    if not datasource_id:
        raise HTTPException(status_code=400, detail='Analysis tab missing datasource.id')
    if not isinstance(steps, list):
        raise HTTPException(status_code=400, detail='Analysis tab steps must be a list')
    config = datasource.get('config') or {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail='Analysis tab datasource.config must be a dict')
    branch = config.get('branch')
    if not isinstance(branch, str) or not branch.strip():
        raise HTTPException(status_code=400, detail='Analysis tab datasource.config.branch is required')
    output_config = selected.get('output')
    if not isinstance(output_config, dict):
        raise HTTPException(status_code=400, detail='Analysis tab output must be a dict')

    preview = compute_service.preview_step(
        session=session,
        target_step_id=steps[-1]['id'] if steps else 'source',
        row_limit=50,
        page=1,
        analysis_id=analysis_id_value,
        analysis_pipeline=analysis_payload,
        tab_id=None,
    )

    return {
        'schema': preview.column_types,
        'rows': preview.data,
        'row_count': preview.total_rows,
    }


@router.delete('/{analysis_id}/datasources/{datasource_id}', status_code=204)
@handle_errors(operation='unlink datasource', value_error_status=400)
@deterministic_tool
def unlink_datasource(
    analysis_id: AnalysisId,
    datasource_id: DataSourceId,
    session: Session = Depends(get_db),
):
    """Remove a datasource link from an analysis and its associated tab."""
    service.unlink_datasource(session, parse_analysis_id(analysis_id), parse_datasource_id(datasource_id))
    return None


class AddStepBody(BaseModel):
    type: StepType = Field(description='The step type. Use GET /step-types to see valid types.')
    config: dict = Field(default_factory=dict, description='Step configuration. Schema depends on step type.')
    position: int | None = Field(None, description='Insert position (0-based index). Omit to append at end.')
    depends_on: list[str] = Field(default_factory=list, description='List of step IDs this step depends on.')


class UpdateStepBody(BaseModel):
    type: StepType | None = Field(None, description='New step type. Omit to keep current type.')
    config: dict | None = Field(None, description='New config. Omit to keep current config.')


@router.post('/{analysis_id}/tabs/{tab_id}/steps')
@handle_errors(operation='add step', value_error_status=400)
@deterministic_tool
def add_step(
    analysis_id: AnalysisId,
    tab_id: str,
    data: AddStepBody,
    session: Session = Depends(get_db),
):
    """Add a new pipeline step to a tab in an analysis.

    The step type must be valid (use GET /step-types to see options). Config is validated
    against the step type's schema. Returns the created step with its generated ID.
    Steps are appended to the end by default; use 'position' to insert at a specific index.
    """
    model = get_config_model(data.type)
    if model:
        model.model_validate(data.config)
    return service.add_step(
        session,
        parse_analysis_id(analysis_id),
        tab_id,
        data.type,
        data.config,
        data.position,
        data.depends_on,
    )


@router.put('/{analysis_id}/tabs/{tab_id}/steps/{step_id}')
@handle_errors(operation='update step', value_error_status=400)
@deterministic_tool
def update_step(
    analysis_id: AnalysisId,
    tab_id: str,
    step_id: str,
    data: UpdateStepBody,
    session: Session = Depends(get_db),
):
    """Update a pipeline step's type and/or config.

    Provide only the fields you want to change.
    If changing type, also provide the new config matching the new type's schema.
    """
    effective = data.type
    if effective and data.config:
        model = get_config_model(effective)
        if model:
            model.model_validate(data.config)
    return service.update_step(
        session,
        parse_analysis_id(analysis_id),
        tab_id,
        step_id,
        data.config,
        data.type,
    )


@router.delete('/{analysis_id}/tabs/{tab_id}/steps/{step_id}', status_code=204)
@handle_errors(operation='remove step', value_error_status=400)
@deterministic_tool
def remove_step(
    analysis_id: AnalysisId,
    tab_id: str,
    step_id: str,
    session: Session = Depends(get_db),
):
    """Remove a pipeline step from a tab. Also cleans up depends_on references in other steps that depended on the removed step."""
    service.remove_step(
        session,
        parse_analysis_id(analysis_id),
        tab_id,
        step_id,
    )
    return None
