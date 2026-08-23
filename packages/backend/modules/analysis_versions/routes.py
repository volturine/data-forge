from fastapi import Depends, HTTPException, Response
from sqlmodel import Session

from backend_core.database import get_db
from backend_core.error_handlers import handle_errors
from backend_core.persistence.analysis.models import Analysis
from backend_core.validation import AnalysisId, parse_analysis_id
from modules.analysis import schemas as analysis_schemas, service as analysis_service
from modules.analysis.ownership import ensure_analysis_mutation_allowed
from modules.analysis.revisions import require as require_analysis_revision, set_response_headers as set_analysis_revision_headers
from modules.analysis_versions import schemas, service
from modules.auth.dependencies import get_current_user, get_current_user_id
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/analysis', tags=['analysis-versions'], dependencies=[Depends(get_current_user)])


@router.get(
    '/{analysis_id}/versions',
    response_model=list[schemas.AnalysisVersionSummary],
    mcp=True,
)
@handle_errors(operation='list analysis versions')
def list_versions(
    analysis_id: AnalysisId,
    session: Session = Depends(get_db),
):
    """List all saved versions of an analysis, ordered by version number.

    Returns lightweight summaries (no pipeline_definition). Use GET /analysis/{id}/versions/{version}
    to get the full pipeline_definition for a specific version.
    """
    return service.list_versions(session, parse_analysis_id(analysis_id))


@router.get(
    '/{analysis_id}/versions/{version}',
    response_model=schemas.AnalysisVersionResponse,
    mcp=True,
)
@handle_errors(operation='get analysis version', value_error_status=404)
def get_version(
    analysis_id: AnalysisId,
    version: int,
    session: Session = Depends(get_db),
):
    """Get a specific version of an analysis by version number. Returns the full pipeline_definition snapshot."""
    result = service.get_version(session, parse_analysis_id(analysis_id), version)
    if not result:
        raise HTTPException(status_code=404, detail='Version not found')
    return result


@router.delete('/{analysis_id}/versions/{version}', mcp=True)
@handle_errors(operation='delete analysis version')
def delete_version(
    analysis_id: AnalysisId,
    version: int,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Delete a specific version of an analysis by version number."""
    parsed_id = parse_analysis_id(analysis_id)
    ensure_analysis_mutation_allowed(session, parsed_id, user_id)
    service.delete_version(session, parsed_id, version)


@router.patch(
    '/{analysis_id}/versions/{version}',
    response_model=schemas.AnalysisVersionResponse,
    mcp=True,
)
@handle_errors(operation='rename analysis version')
def rename_version(
    analysis_id: AnalysisId,
    version: int,
    body: schemas.AnalysisVersionUpdate,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Rename a version (set a descriptive label like 'before refactor'). Only the name field can be changed."""
    parsed_id = parse_analysis_id(analysis_id)
    ensure_analysis_mutation_allowed(session, parsed_id, user_id)
    return service.rename_version(session, parsed_id, version, body.name)


@router.post(
    '/{analysis_id}/versions/{version}/restore',
    response_model=analysis_schemas.AnalysisResponseSchema,
    mcp=True,
)
@handle_errors(operation='restore analysis version')
def restore_version(
    analysis_id: AnalysisId,
    version: int,
    response: Response,
    _analysis: Analysis = Depends(require_analysis_revision),
    session: Session = Depends(get_db),
):
    """Restore an analysis to a specific version. Creates a new version with the restored pipeline_definition.

    The current state is saved as a version before restoring, so you can always undo.
    """
    restored = service.restore_version(session, parse_analysis_id(analysis_id), version)
    set_analysis_revision_headers(response, restored)
    return analysis_service.get_analysis(session, restored.id)
