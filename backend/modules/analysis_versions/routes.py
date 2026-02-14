from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.database import get_db
from modules.analysis import schemas as analysis_schemas
from modules.analysis_versions import schemas, service

router = APIRouter(prefix='/analysis', tags=['analysis-versions'])


@router.get('/{analysis_id}/versions', response_model=list[schemas.AnalysisVersionResponse])
def list_versions(
    analysis_id: str,
    session: Session = Depends(get_db),
):
    try:
        return service.list_versions(session, analysis_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to list analysis versions: {str(e)}')


@router.get('/{analysis_id}/versions/{version}', response_model=schemas.AnalysisVersionResponse)
def get_version(
    analysis_id: str,
    version: int,
    session: Session = Depends(get_db),
):
    result = service.get_version(session, analysis_id, version)
    if not result:
        raise HTTPException(status_code=404, detail='Version not found')
    return result


@router.patch('/{analysis_id}/versions/{version}', response_model=schemas.AnalysisVersionResponse)
def rename_version(
    analysis_id: str,
    version: int,
    body: schemas.AnalysisVersionUpdate,
    session: Session = Depends(get_db),
):
    try:
        return service.rename_version(session, analysis_id, version, body.name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to rename version: {str(e)}')


@router.post('/{analysis_id}/versions/{version}/restore', response_model=analysis_schemas.AnalysisResponseSchema)
def restore_version(
    analysis_id: str,
    version: int,
    session: Session = Depends(get_db),
):
    try:
        return service.restore_version(session, analysis_id, version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to restore analysis version: {str(e)}')
