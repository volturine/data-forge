import contextlib

from fastapi import Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from backend_core.database import get_db
from backend_core.dependencies import RuntimeAvailabilityProbe, get_runtime_availability_probe
from backend_core.domain.analysis.step_types import is_step_type
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.error_handlers import handle_errors
from backend_core.persistence.analysis.models import Analysis
from backend_core.validation import AnalysisId, parse_analysis_id
from dataforge_protocol import compute_pb2, enums_pb2
from modules.analysis import schemas, service
from modules.analysis.pipeline_compiler import compile_step
from modules.analysis.revisions import (
    etag as analysis_etag,
    matches_if_none_match,
    require as require_analysis_revision,
    set_response_headers as set_analysis_revision_headers,
    version as analysis_version,
)
from modules.analysis.step_schemas import get_step_catalog
from modules.auth.dependencies import get_current_user, get_current_user_id
from modules.auth.models import User
from modules.compute import executor_client
from modules.export import service as export_service
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/analysis', tags=['analysis'], dependencies=[Depends(get_current_user)])


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
    user: User = Depends(get_current_user),
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
    owner_id = user.id
    return service.create_analysis(session, data, owner_id=owner_id)


@router.get('/templates', response_model=list[schemas.AnalysisTemplateSummarySchema], mcp=True)
@handle_errors(operation='list analysis templates', value_error_status=404)
async def list_analysis_templates():
    """List built-in analysis templates available in the guided creation flow."""
    return service.list_analysis_templates()


@router.get(
    '/templates/{template_id}',
    response_model=schemas.AnalysisTemplateDetailSchema,
    mcp=True,
)
@handle_errors(operation='get analysis template', value_error_status=404)
async def get_analysis_template(template_id: str):
    """Get one analysis template including the step skeleton used for creation."""
    return service.get_analysis_template(template_id)


@router.post('/generate', response_model=schemas.GeneratedAnalysisResponseSchema, mcp=True)
@handle_errors(operation='generate analysis pipeline', value_error_status=400)
async def generate_analysis_pipeline(
    data: schemas.GenerateAnalysisSchema,
    session: Session = Depends(get_db),
):
    """Generate an analysis pipeline skeleton from a natural-language description."""
    return service.generate_analysis_pipeline(session, data)


@router.post('/import', response_model=schemas.AnalysisResponseSchema, mcp=True)
@handle_errors(operation='import analysis', value_error_status=400)
async def import_analysis(
    data: schemas.ImportAnalysisSchema,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Import an analysis pipeline definition and persist it as a new analysis."""
    owner_id = user.id
    return service.import_analysis(session, data, owner_id=owner_id)


@router.get('', response_model=list[schemas.AnalysisGalleryItemSchema], mcp=True)
@handle_errors(operation='list analyses')
async def list_analyses(session: Session = Depends(get_db)):
    """List all analyses as gallery items with id, name, and thumbnail metadata."""
    return service.list_analyses(session)


@router.get('/favorites', response_model=list[schemas.AnalysisGalleryItemSchema], mcp=True)
@handle_errors(operation='list favorite analyses')
async def list_favorite_analyses(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List only the current user's favorited analyses."""
    return service.list_favorite_analyses(session, user.id)


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
    if_none_match: str | None = Header(default=None),
    session: Session = Depends(get_db),
):
    """Get a single analysis by ID with full pipeline definition including all tabs and steps."""
    parsed_id = parse_analysis_id(analysis_id)
    current_etag = service.get_analysis_etag(session, parsed_id)
    if matches_if_none_match(if_none_match, current_etag):
        return Response(status_code=304, headers={'ETag': current_etag})
    analysis = service.get_analysis(session, parsed_id)
    response.headers['ETag'] = current_etag
    response.headers['X-Analysis-Version'] = analysis_version(analysis)
    return analysis


@router.post('/{analysis_id}/duplicate', response_model=schemas.AnalysisResponseSchema, mcp=True)
@handle_errors(operation='duplicate analysis', value_error_status=400)
async def duplicate_analysis(
    analysis_id: AnalysisId,
    data: schemas.DuplicateAnalysisSchema,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Duplicate an analysis while regenerating output identities and derived references."""
    owner_id = user.id
    return service.duplicate_analysis(session, parse_analysis_id(analysis_id), data, owner_id=owner_id)


@router.put('/{analysis_id}', response_model=schemas.AnalysisResponseSchema, mcp=True)
@handle_errors(operation='update analysis')
async def update_analysis(
    analysis_id: AnalysisId,
    response: Response,
    data: schemas.AnalysisUpdateSchema,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
):
    """Update an analysis and replace the full tabs array.

    DO NOT call this to add tabs — use POST /analysis/{id}/tabs/{tab_id}/derive instead,
    then add steps via POST /analysis/{id}/tabs/{tab_id}/steps.
    """
    analysis_id_value = parse_analysis_id(analysis_id)
    updated = service.update_analysis(session, analysis_id_value, data)
    response.headers['ETag'] = analysis_etag(updated)
    response.headers['X-Analysis-Version'] = analysis_version(updated)
    return updated


@router.post(
    '/{analysis_id}/favorite',
    response_model=schemas.AnalysisFavoriteStatusSchema,
    mcp=True,
)
@handle_errors(operation='favorite analysis', value_error_status=404)
async def favorite_analysis(
    analysis_id: AnalysisId,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_db),
):
    """Mark an analysis as favorite for the current user."""
    return service.set_favorite(session, parse_analysis_id(analysis_id), user_id, True)


@router.delete(
    '/{analysis_id}/favorite',
    response_model=schemas.AnalysisFavoriteStatusSchema,
    mcp=True,
    mcp_confirm_required=True,
)
@handle_errors(operation='unfavorite analysis', value_error_status=404)
async def unfavorite_analysis(
    analysis_id: AnalysisId,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_db),
):
    """Remove an analysis from the current user's favorites."""
    return service.set_favorite(session, parse_analysis_id(analysis_id), user_id, False)


@router.delete('/{analysis_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='delete analysis', value_error_status=404)
async def delete_analysis(
    analysis_id: AnalysisId,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Delete an analysis and its associated data."""
    analysis_id_value = parse_analysis_id(analysis_id)
    try:
        service.delete_analysis(session, analysis_id_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # The deletion is committed above; runtime teardown must not delay its response.
    with contextlib.suppress(HTTPException):
        executor_client.request_engine_shutdown(
            session,
            identity=compute_pb2.EngineIdentity(
                scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
                reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
                analysis_id=analysis_id_value,
                resource_id=analysis_id_value,
            ),
            runtime_probe=runtime_probe,
        )


@router.post('/{analysis_id}/preview', mcp=True)
@handle_errors(operation='preview analysis', value_error_status=400)
async def preview_analysis(
    analysis_id: AnalysisId,
    request: Request,
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
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

    preview = await executor_client.preview_step(
        session,
        compute_schemas.StepPreviewRequest(
            analysis_id=analysis_id_value,
            target_step_id=steps[-1]['id'] if steps else 'source',
            analysis_pipeline=compute_schemas.AnalysisPipelinePayload.model_validate(analysis_payload),
            row_limit=50,
            page=1,
            tab_id=None,
        ),
        runtime_probe=runtime_probe,
    )

    return {
        'schema': preview.column_types,
        'rows': preview.data,
        'row_count': preview.total_rows,
    }


@router.post(
    '/{analysis_id}/export-code',
    response_model=schemas.CodeExportResponseSchema,
    mcp=True,
)
@handle_errors(operation='export analysis code', value_error_status=400)
async def export_analysis_code(
    analysis_id: AnalysisId,
    data: schemas.CodeExportRequestSchema,
    session: Session = Depends(get_db),
):
    """Export an analysis (or specific tab) as executable Polars Python or SQL."""
    return export_service.export_analysis_code(
        session,
        parse_analysis_id(analysis_id),
        format_name=data.format,
        tab_id=data.tab_id,
    )


class AddStepBody(BaseModel):
    type: str = Field(description='The step type. Use GET /step-types to see valid types.')
    config: dict = Field(
        default_factory=dict,
        description='Step configuration. Schema depends on step type.',
    )
    position: int | None = Field(None, description='Insert position (0-based index). Omit to append at end.')
    depends_on: list[str] = Field(default_factory=list, description='List of step IDs this step depends on.')

    @field_validator('type')
    @classmethod
    def validate_type(cls, value: str) -> str:
        if not is_step_type(value):
            raise ValueError(f"Unknown step type '{value}'")
        return value


class UpdateStepBody(BaseModel):
    type: str | None = Field(None, description='New step type. Omit to keep current type.')
    config: dict | None = Field(None, description='New config. Omit to keep current config.')

    @field_validator('type')
    @classmethod
    def validate_type(cls, value: str | None) -> str | None:
        if value is not None and not is_step_type(value):
            raise ValueError(f"Unknown step type '{value}'")
        return value


@router.post('/{analysis_id}/tabs/{tab_id}/steps', mcp=True)
@handle_errors(operation='add step', value_error_status=400)
async def add_step(
    analysis_id: AnalysisId,
    tab_id: str,
    data: AddStepBody,
    response: Response,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
):
    """Add a new pipeline step to a tab in an analysis.

    The step type must be valid (use GET /step-types to see options). Config is validated
    against the step type's schema. Returns the created step with its generated ID.
    Steps are appended to the end by default; use 'position' to insert at a specific index.
    """
    compiled = compile_step(
        step_id='new-step',
        step_type=data.type,
        config=data.config,
        depends_on=data.depends_on,
        is_applied=None,
    )
    result = service.add_step(
        session,
        parse_analysis_id(analysis_id),
        tab_id,
        data.type,
        compiled.config,
        data.position,
        data.depends_on,
    )
    set_analysis_revision_headers(response, _analysis)
    return result


@router.put('/{analysis_id}/tabs/{tab_id}/steps/{step_id}', mcp=True)
@handle_errors(operation='update step', value_error_status=400)
async def update_step(
    analysis_id: AnalysisId,
    tab_id: str,
    step_id: str,
    data: UpdateStepBody,
    response: Response,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
):
    """Update a pipeline step's type and/or config.

    Provide only the fields you want to change.
    If changing type, also provide the new config matching the new type's schema.
    """
    analysis_id_value = parse_analysis_id(analysis_id)
    normalized_config = data.config
    if data.type and data.config:
        normalized_config = compile_step(
            step_id=step_id,
            step_type=data.type,
            config=data.config,
            depends_on=[],
            is_applied=None,
        ).config
    elif data.type and not data.config:
        existing = service.get_step(session, analysis_id_value, tab_id, step_id)
        compile_step(
            step_id=step_id,
            step_type=data.type,
            config=existing.config,
            depends_on=[],
            is_applied=None,
        )
    elif data.config and not data.type:
        existing = service.get_step(session, analysis_id_value, tab_id, step_id)
        existing_type = existing.type
        if existing_type:
            normalized_config = compile_step(
                step_id=step_id,
                step_type=existing_type,
                config=data.config,
                depends_on=[],
                is_applied=None,
            ).config
    result = service.update_step(
        session,
        analysis_id_value,
        tab_id,
        step_id,
        normalized_config,
        data.type,
    )
    set_analysis_revision_headers(response, _analysis)
    return result


@router.delete('/{analysis_id}/tabs/{tab_id}/steps/{step_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='remove step', value_error_status=400)
async def remove_step(
    analysis_id: AnalysisId,
    tab_id: str,
    step_id: str,
    response: Response,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
):
    """Remove a pipeline step from a tab. Also cleans up depends_on references in other steps that depended on the removed step."""
    service.remove_step(
        session,
        parse_analysis_id(analysis_id),
        tab_id,
        step_id,
    )
    set_analysis_revision_headers(response, _analysis)


class DeriveTabBody(BaseModel):
    name: str | None = Field(None, description='Name for the new derived tab. Defaults to "Derived N".')


@router.post('/{analysis_id}/tabs/{tab_id}/derive', mcp=True)
@handle_errors(operation='derive tab', value_error_status=400)
async def derive_tab(
    analysis_id: AnalysisId,
    tab_id: str,
    data: DeriveTabBody,
    response: Response,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
):
    """Create a new tab whose datasource is the given tab's output result_id.

    This chains the output of an existing tab into a new tab for further processing.
    The source tab must have a computed output.result_id. The new tab starts with no steps.
    """
    result = service.derive_tab(session, parse_analysis_id(analysis_id), tab_id, data.name)
    set_analysis_revision_headers(response, _analysis)
    return result


class DuplicateTabBody(BaseModel):
    name: str | None = Field(None, description='Name for the duplicated tab. Defaults to "<source> Copy".')


@router.post('/{analysis_id}/tabs/{tab_id}/duplicate', mcp=True)
@handle_errors(operation='duplicate tab', value_error_status=400)
async def duplicate_tab(
    analysis_id: AnalysisId,
    tab_id: str,
    data: DuplicateTabBody,
    response: Response,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
):
    """Duplicate a tab inside the same analysis.

    The duplicate is inserted immediately after the source tab, keeps the same datasource and step logic,
    and receives fresh tab/step/output IDs so it can evolve independently.
    """
    result = service.duplicate_tab(session, parse_analysis_id(analysis_id), tab_id, data.name)
    set_analysis_revision_headers(response, _analysis)
    return result
