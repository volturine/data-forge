import contextlib

from fastapi import Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from core.database import get_db
from core.dependencies import get_manager, get_optional_lock_owner_id
from core.error_handlers import handle_errors
from core.validation import AnalysisId, parse_analysis_id
from modules.analysis import schemas, service
from modules.analysis.step_schemas import StepType, get_config_model, get_step_catalog
from modules.auth.dependencies import get_optional_user
from modules.auth.models import User
from modules.compute import service as compute_service
from modules.compute.manager import ProcessManager
from modules.locks import service as lock_service
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/analysis', tags=['analysis'])


def _analysis_etag(analysis: schemas.AnalysisResponseSchema) -> str:
    return f'"analysis-{analysis.id}-{analysis.updated_at.isoformat()}"'


def _analysis_version(analysis: schemas.AnalysisResponseSchema) -> str:
    return analysis.updated_at.isoformat()


def _validate_if_match(current_version: str, current_etag: str, if_match: str | None) -> None:
    if if_match is None:
        return
    normalized = if_match.strip()
    if normalized == '*':
        return
    if normalized == current_version:
        return
    if normalized == current_etag:
        return
    raise HTTPException(status_code=412, detail='Analysis version mismatch')


async def require_analysis_lock(
    analysis_id: AnalysisId,
    session: Session = Depends(get_db),
    owner_id: str | None = Depends(get_optional_lock_owner_id),
) -> None:
    try:
        lock_service.ensure_mutation_lock(session, 'analysis', parse_analysis_id(analysis_id), owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/validate', mcp=True)
@handle_errors(operation='validate analysis', value_error_status=400)
async def validate_analysis(
    data: schemas.AnalysisCreateSchema,
    session: Session = Depends(get_db),
):
    """Validate analysis payload without persisting."""
    return service.validate_analysis(session, data)


@router.post('', response_model=schemas.AnalysisResponseSchema, mcp=True)
@handle_errors(operation='create analysis', value_error_status=400)
async def create_analysis(
    data: schemas.AnalysisCreateSchema,
    session: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Create a new analysis pipeline.

    IMPORTANT: Before calling this, use GET /api/v1/datasource to list existing datasources
    and obtain a valid datasource ID. `tabs[].datasource.id` must reference an existing
    datasource ID. Do NOT invent datasource IDs.

    `tabs[].output.result_id` must be a NEW UUID (uuid4) unique to each tab.
    This is NOT a datasource — generate a fresh uuid4 for each tab's result_id.

    Each tab requires: a datasource (with id and config.branch), an output
    (with result_id, format, filename), and optionally steps.
    Use GET /api/v1/analysis/step-types to discover valid step types and their config schemas.
    """
    owner_id = user.id if user else None
    return service.create_analysis(session, data, owner_id=owner_id)


@router.get('', response_model=list[schemas.AnalysisGalleryItemSchema], mcp=True)
@handle_errors(operation='list analyses')
async def list_analyses(session: Session = Depends(get_db)):
    """List all analyses as gallery items with id, name, thumbnail, and timestamps."""
    return service.list_analyses(session)


@router.get('/step-types', mcp=True)
@handle_errors(operation='list step types')
async def list_step_types():
    """List all available pipeline step types with descriptions and config schemas.

    Use this to discover what operations are available and what configuration
    each requires before adding steps to an analysis.
    """
    return get_step_catalog()


@router.get('/{analysis_id}', response_model=schemas.AnalysisResponseSchema, mcp=True)
@handle_errors(operation='get analysis', value_error_status=404)
async def get_analysis(
    analysis_id: AnalysisId,
    response: Response,
    session: Session = Depends(get_db),
):
    """Get a single analysis by ID with full pipeline definition including all tabs and steps."""
    analysis = service.get_analysis(session, parse_analysis_id(analysis_id))
    response.headers['ETag'] = _analysis_etag(analysis)
    response.headers['X-Analysis-Version'] = _analysis_version(analysis)
    return analysis


@router.put('/{analysis_id}', response_model=schemas.AnalysisResponseSchema, mcp=True)
@handle_errors(operation='update analysis')
async def update_analysis(
    analysis_id: AnalysisId,
    response: Response,
    data: schemas.AnalysisUpdateSchema,
    if_match: str | None = Header(default=None, alias='If-Match'),
    _lock: None = Depends(require_analysis_lock),
    session: Session = Depends(get_db),
):
    """Update an analysis and replace the full tabs array.

    DO NOT call this to add tabs — use POST /analysis/{id}/tabs/{tab_id}/derive instead,
    then add steps via POST /analysis/{id}/tabs/{tab_id}/steps.
    """
    analysis_id_value = parse_analysis_id(analysis_id)
    try:
        analysis = service.get_analysis(session, analysis_id_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _validate_if_match(_analysis_version(analysis), _analysis_etag(analysis), if_match)

    updated = service.update_analysis(session, analysis_id_value, data)
    response.headers['ETag'] = _analysis_etag(updated)
    response.headers['X-Analysis-Version'] = _analysis_version(updated)
    return updated


@router.delete('/{analysis_id}', status_code=204, mcp=True)
@handle_errors(operation='delete analysis', value_error_status=404)
async def delete_analysis(
    analysis_id: AnalysisId,
    _lock: None = Depends(require_analysis_lock),
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
):
    """Delete an analysis and its associated data."""
    analysis_id_value = parse_analysis_id(analysis_id)
    try:
        service.delete_analysis(session, analysis_id_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if manager.get_engine(analysis_id_value):
        manager.shutdown_engine(analysis_id_value)


@router.post('/{analysis_id}/preview', mcp=True)
@handle_errors(operation='preview analysis', value_error_status=400)
async def preview_analysis(
    analysis_id: AnalysisId,
    request: Request,
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
):
    """Preview the analysis pipeline and return results with schema, rows, and row count."""
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
        manager=manager,
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


class AddStepBody(BaseModel):
    type: StepType = Field(description='The step type. Use GET /step-types to see valid types.')
    config: dict = Field(default_factory=dict, description='Step configuration. Schema depends on step type.')
    position: int | None = Field(None, description='Insert position (0-based index). Omit to append at end.')
    depends_on: list[str] = Field(default_factory=list, description='List of step IDs this step depends on.')


class UpdateStepBody(BaseModel):
    type: StepType | None = Field(None, description='New step type. Omit to keep current type.')
    config: dict | None = Field(None, description='New config. Omit to keep current config.')


@router.post('/{analysis_id}/tabs/{tab_id}/steps', mcp=True)
@handle_errors(operation='add step', value_error_status=400)
async def add_step(
    analysis_id: AnalysisId,
    tab_id: str,
    data: AddStepBody,
    _lock: None = Depends(require_analysis_lock),
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


@router.put('/{analysis_id}/tabs/{tab_id}/steps/{step_id}', mcp=True)
@handle_errors(operation='update step', value_error_status=400)
async def update_step(
    analysis_id: AnalysisId,
    tab_id: str,
    step_id: str,
    data: UpdateStepBody,
    _lock: None = Depends(require_analysis_lock),
    session: Session = Depends(get_db),
):
    """Update a pipeline step's type and/or config.

    Provide only the fields you want to change.
    If changing type, also provide the new config matching the new type's schema.
    """
    analysis_id_value = parse_analysis_id(analysis_id)
    if data.type and data.config:
        model = get_config_model(data.type)
        if model:
            model.model_validate(data.config)
    elif data.type and not data.config:
        existing = service.get_step(session, analysis_id_value, tab_id, step_id)
        model = get_config_model(data.type)
        if model:
            model.model_validate(existing.config)
    elif data.config and not data.type:
        existing = service.get_step(session, analysis_id_value, tab_id, step_id)
        existing_type = existing.type
        if existing_type:
            model = get_config_model(existing_type)
            if model:
                model.model_validate(data.config)
    return service.update_step(
        session,
        analysis_id_value,
        tab_id,
        step_id,
        data.config,
        data.type,
    )


@router.delete('/{analysis_id}/tabs/{tab_id}/steps/{step_id}', status_code=204, mcp=True)
@handle_errors(operation='remove step', value_error_status=400)
async def remove_step(
    analysis_id: AnalysisId,
    tab_id: str,
    step_id: str,
    _lock: None = Depends(require_analysis_lock),
    session: Session = Depends(get_db),
):
    """Remove a pipeline step from a tab. Also cleans up depends_on references in other steps that depended on the removed step."""
    service.remove_step(
        session,
        parse_analysis_id(analysis_id),
        tab_id,
        step_id,
    )


class DeriveTabBody(BaseModel):
    name: str | None = Field(None, description='Name for the new derived tab. Defaults to "Derived N".')


@router.post('/{analysis_id}/tabs/{tab_id}/derive', mcp=True)
@handle_errors(operation='derive tab', value_error_status=400)
async def derive_tab(
    analysis_id: AnalysisId,
    tab_id: str,
    data: DeriveTabBody,
    _lock: None = Depends(require_analysis_lock),
    session: Session = Depends(get_db),
):
    """Create a new tab whose datasource is the given tab's output result_id.

    This chains the output of an existing tab into a new tab for further processing.
    The source tab must have a computed output.result_id. The new tab starts with no steps.
    """
    return service.derive_tab(session, parse_analysis_id(analysis_id), tab_id, data.name)
