from core.database import get_db
from fastapi import Depends, HTTPException
from sqlmodel import Session

from backend_core.dependencies import get_optional_lock_owner_id
from backend_core.error_handlers import handle_errors
from backend_core.validation import AnalysisId, parse_analysis_id
from modules.analysis import schemas as analysis_schemas
from modules.analysis import service as analysis_service
from modules.analysis_versions import schemas, service
from modules.locks import service as lock_service
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix="/analysis", tags=["analysis-versions"])


def require_analysis_lock(
    analysis_id: AnalysisId,
    session: Session = Depends(get_db),
    owner_id: str | None = Depends(get_optional_lock_owner_id),
) -> None:
    try:
        lock_service.ensure_mutation_lock(session, "analysis", parse_analysis_id(analysis_id), owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/{analysis_id}/versions",
    response_model=list[schemas.AnalysisVersionSummary],
    mcp=True,
)
@handle_errors(operation="list analysis versions")
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
    "/{analysis_id}/versions/{version}",
    response_model=schemas.AnalysisVersionResponse,
    mcp=True,
)
@handle_errors(operation="get analysis version", value_error_status=404)
def get_version(
    analysis_id: AnalysisId,
    version: int,
    session: Session = Depends(get_db),
):
    """Get a specific version of an analysis by version number. Returns the full pipeline_definition snapshot."""
    result = service.get_version(session, parse_analysis_id(analysis_id), version)
    if not result:
        raise HTTPException(status_code=404, detail="Version not found")
    return result


@router.delete("/{analysis_id}/versions/{version}", mcp=True)
@handle_errors(operation="delete analysis version")
def delete_version(
    analysis_id: AnalysisId,
    version: int,
    _lock: None = Depends(require_analysis_lock),
    session: Session = Depends(get_db),
):
    """Delete a specific version of an analysis by version number."""
    service.delete_version(session, parse_analysis_id(analysis_id), version)


@router.patch(
    "/{analysis_id}/versions/{version}",
    response_model=schemas.AnalysisVersionResponse,
    mcp=True,
)
@handle_errors(operation="rename analysis version")
def rename_version(
    analysis_id: AnalysisId,
    version: int,
    body: schemas.AnalysisVersionUpdate,
    _lock: None = Depends(require_analysis_lock),
    session: Session = Depends(get_db),
):
    """Rename a version (set a descriptive label like 'before refactor'). Only the name field can be changed."""
    return service.rename_version(session, parse_analysis_id(analysis_id), version, body.name)


@router.post(
    "/{analysis_id}/versions/{version}/restore",
    response_model=analysis_schemas.AnalysisResponseSchema,
    mcp=True,
)
@handle_errors(operation="restore analysis version")
def restore_version(
    analysis_id: AnalysisId,
    version: int,
    _lock: None = Depends(require_analysis_lock),
    session: Session = Depends(get_db),
):
    """Restore an analysis to a specific version. Creates a new version with the restored pipeline_definition.

    The current state is saved as a version before restoring, so you can always undo.
    """
    restored = service.restore_version(session, parse_analysis_id(analysis_id), version)
    return analysis_service.get_analysis(session, restored.id)
