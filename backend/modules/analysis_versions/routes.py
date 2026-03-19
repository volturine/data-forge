from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import AnalysisId, parse_analysis_id
from modules.analysis import schemas as analysis_schemas
from modules.analysis_versions import schemas, service
from modules.mcp.decorators import deterministic_tool

router = APIRouter(prefix='/analysis', tags=['analysis-versions'])


@router.get('/{analysis_id}/versions', response_model=list[schemas.AnalysisVersionSummary])
@handle_errors(operation='list analysis versions')
@deterministic_tool
def list_versions(
    analysis_id: AnalysisId,
    session: Session = Depends(get_db),
):
    """List all saved versions of an analysis, ordered by version number.

    Returns lightweight summaries (no pipeline_definition). Use GET /analysis/{id}/versions/{version}
    to get the full pipeline_definition for a specific version.
    """
    return service.list_versions(session, parse_analysis_id(analysis_id))


@router.get('/{analysis_id}/versions/{version}', response_model=schemas.AnalysisVersionResponse)
@handle_errors(operation='get analysis version', value_error_status=404)
@deterministic_tool
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


@router.patch('/{analysis_id}/versions/{version}', response_model=schemas.AnalysisVersionResponse)
@handle_errors(operation='rename analysis version')
@deterministic_tool
def rename_version(
    analysis_id: AnalysisId,
    version: int,
    body: schemas.AnalysisVersionUpdate,
    session: Session = Depends(get_db),
):
    """Rename a version (set a descriptive label like 'before refactor'). Only the name field can be changed."""
    return service.rename_version(session, parse_analysis_id(analysis_id), version, body.name)


@router.post('/{analysis_id}/versions/{version}/restore', response_model=analysis_schemas.AnalysisResponseSchema)
@handle_errors(operation='restore analysis version')
@deterministic_tool
def restore_version(
    analysis_id: AnalysisId,
    version: int,
    session: Session = Depends(get_db),
):
    """Restore an analysis to a specific version. Creates a new version with the restored pipeline_definition.

    The current state is saved as a version before restoring, so you can always undo.
    """
    return service.restore_version(session, parse_analysis_id(analysis_id), version)
