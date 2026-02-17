from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import AnalysisId, parse_analysis_id
from modules.analysis import schemas as analysis_schemas
from modules.analysis_versions import schemas, service

router = APIRouter(prefix='/analysis', tags=['analysis-versions'])


@router.get('/{analysis_id}/versions', response_model=list[schemas.AnalysisVersionResponse])
@handle_errors(operation='list analysis versions')
def list_versions(
    analysis_id: AnalysisId,
    session: Session = Depends(get_db),
):
    return service.list_versions(session, parse_analysis_id(analysis_id))


@router.get('/{analysis_id}/versions/{version}', response_model=schemas.AnalysisVersionResponse)
@handle_errors(operation='get analysis version', value_error_status=404)
def get_version(
    analysis_id: AnalysisId,
    version: int,
    session: Session = Depends(get_db),
):
    result = service.get_version(session, parse_analysis_id(analysis_id), version)
    if not result:
        raise HTTPException(status_code=404, detail='Version not found')
    return result


@router.patch('/{analysis_id}/versions/{version}', response_model=schemas.AnalysisVersionResponse)
@handle_errors(operation='rename analysis version')
def rename_version(
    analysis_id: AnalysisId,
    version: int,
    body: schemas.AnalysisVersionUpdate,
    session: Session = Depends(get_db),
):
    return service.rename_version(session, parse_analysis_id(analysis_id), version, body.name)


@router.post('/{analysis_id}/versions/{version}/restore', response_model=analysis_schemas.AnalysisResponseSchema)
@handle_errors(operation='restore analysis version')
def restore_version(
    analysis_id: AnalysisId,
    version: int,
    session: Session = Depends(get_db),
):
    return service.restore_version(session, parse_analysis_id(analysis_id), version)
