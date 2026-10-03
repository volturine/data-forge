from fastapi import Depends, Header, HTTPException, Response
from sqlmodel import Session

from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import run_db
from backend_core.dependencies import get_optional_lock_owner_id
from backend_core.error_handlers import handle_errors
from backend_core.validation import AnalysisId, parse_analysis_id
from modules.analysis import schemas as analysis_schemas, service as analysis_service
from modules.analysis.ownership import ensure_analysis_mutation_allowed
from modules.analysis.revisions import (
    require as require_analysis_revision,
    set_response_headers as set_analysis_revision_headers,
)
from modules.analysis_versions import schemas, service
from modules.auth.dependencies import get_current_user, get_current_user_id, get_optional_user_id
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/analysis', tags=['analysis-versions'], dependencies=[Depends(get_current_user)])


def _delete_version(
    session: Session,
    analysis_id: str,
    version: int,
    if_match: str | None,
    owner_id: str | None,
    user_id: str | None,
) -> None:
    require_analysis_revision(analysis_id, if_match, session, owner_id, user_id)
    ensure_analysis_mutation_allowed(session, analysis_id, user_id)
    service.delete_version(session, analysis_id, version)


def _rename_version(
    session: Session,
    analysis_id: str,
    version: int,
    name: str,
    if_match: str | None,
    owner_id: str | None,
    user_id: str | None,
):
    require_analysis_revision(analysis_id, if_match, session, owner_id, user_id)
    ensure_analysis_mutation_allowed(session, analysis_id, user_id)
    return service.rename_version(session, analysis_id, version, name)


def _restore_version(
    session: Session,
    analysis_id: str,
    version: int,
    if_match: str | None,
    owner_id: str | None,
    user_id: str | None,
) -> analysis_schemas.AnalysisResponseSchema:
    require_analysis_revision(analysis_id, if_match, session, owner_id, user_id)
    restored = service.restore_version(session, analysis_id, version)
    return analysis_service.get_analysis(session, restored.id)


@router.get(
    '/{analysis_id}/versions',
    response_model=list[schemas.AnalysisVersionSummary],
    mcp=True,
)
@handle_errors(operation='list analysis versions')
async def list_versions(analysis_id: AnalysisId):
    """List all saved versions of an analysis, ordered by version number.

    Returns lightweight summaries (no pipeline_definition). Use GET /analysis/{id}/versions/{version}
    to get the full pipeline_definition for a specific version.
    """
    return await run_api_blocking(run_db, service.list_versions, parse_analysis_id(analysis_id))


@router.get(
    '/{analysis_id}/versions/{version}',
    response_model=schemas.AnalysisVersionResponse,
    mcp=True,
)
@handle_errors(operation='get analysis version', value_error_status=404)
async def get_version(analysis_id: AnalysisId, version: int):
    """Get a specific version of an analysis by version number. Returns the full pipeline_definition snapshot."""
    result = await run_api_blocking(run_db, service.get_version, parse_analysis_id(analysis_id), version)
    if not result:
        raise HTTPException(status_code=404, detail='Version not found')
    return result


@router.delete('/{analysis_id}/versions/{version}', mcp=True)
@handle_errors(operation='delete analysis version')
async def delete_version(
    analysis_id: AnalysisId,
    version: int,
    if_match: str | None = Header(default=None, alias='If-Match'),
    owner_id: str | None = Depends(get_optional_lock_owner_id),
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Delete a specific version of an analysis by version number."""
    await run_api_blocking(
        run_db,
        _delete_version,
        parse_analysis_id(analysis_id),
        version,
        if_match,
        owner_id,
        user_id,
    )


@router.patch(
    '/{analysis_id}/versions/{version}',
    response_model=schemas.AnalysisVersionResponse,
    mcp=True,
)
@handle_errors(operation='rename analysis version')
async def rename_version(
    analysis_id: AnalysisId,
    version: int,
    body: schemas.AnalysisVersionUpdate,
    if_match: str | None = Header(default=None, alias='If-Match'),
    owner_id: str | None = Depends(get_optional_lock_owner_id),
    user_id: str = Depends(get_current_user_id),
):
    """Rename a version (set a descriptive label like 'before refactor'). Only the name field can be changed."""
    return await run_api_blocking(
        run_db,
        _rename_version,
        parse_analysis_id(analysis_id),
        version,
        body.name,
        if_match,
        owner_id,
        user_id,
    )


@router.post(
    '/{analysis_id}/versions/{version}/restore',
    response_model=analysis_schemas.AnalysisResponseSchema,
    mcp=True,
)
@handle_errors(operation='restore analysis version')
async def restore_version(
    analysis_id: AnalysisId,
    version: int,
    response: Response,
    if_match: str | None = Header(default=None, alias='If-Match'),
    owner_id: str | None = Depends(get_optional_lock_owner_id),
    user_id: str | None = Depends(get_optional_user_id),
):
    """Restore an analysis to a specific version. Creates a new version with the restored pipeline_definition.

    The current state is saved as a version before restoring, so you can always undo.
    """
    analysis = await run_api_blocking(
        run_db,
        _restore_version,
        parse_analysis_id(analysis_id),
        version,
        if_match,
        owner_id,
        user_id,
    )
    set_analysis_revision_headers(response, analysis)
    return analysis
