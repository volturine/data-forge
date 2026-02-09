from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.database import get_db
from modules.analysis import schemas, service
from modules.locks import service as lock_service

router = APIRouter(prefix='/analysis', tags=['analysis'])


@router.post('', response_model=schemas.AnalysisResponseSchema)
def create_analysis(
    data: schemas.AnalysisCreateSchema,
    session: Session = Depends(get_db),
):
    """Create a new analysis with pipeline definition."""
    try:
        return service.create_analysis(session, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to create analysis: {str(e)}')


@router.get('', response_model=list[schemas.AnalysisGalleryItemSchema])
def list_analyses(session: Session = Depends(get_db)):
    """List all analyses as gallery items."""
    try:
        return service.list_analyses(session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to list analyses: {str(e)}')


@router.get('/{analysis_id}', response_model=schemas.AnalysisResponseSchema)
def get_analysis(
    analysis_id: str,
    session: Session = Depends(get_db),
):
    """Get a specific analysis by ID."""
    try:
        return service.get_analysis(session, analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get analysis: {str(e)}')


@router.put('/{analysis_id}', response_model=schemas.AnalysisResponseSchema)
def update_analysis(
    analysis_id: str,
    data: schemas.AnalysisUpdateSchema,
    session: Session = Depends(get_db),
):
    """Update an existing analysis."""
    try:
        service.get_analysis(session, analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not data.client_id or not data.lock_token:
        raise HTTPException(status_code=409, detail='Editing lock required')

    try:
        lock_service.validate_lock(session, analysis_id, data.client_id, data.lock_token)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    try:
        return service.update_analysis(session, analysis_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to update analysis: {str(e)}')


@router.delete('/{analysis_id}')
def delete_analysis(
    analysis_id: str,
    session: Session = Depends(get_db),
):
    """Delete an analysis and its associations."""
    try:
        service.delete_analysis(session, analysis_id)
        return {'message': f'Analysis {analysis_id} deleted successfully'}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to delete analysis: {str(e)}')


@router.post('/{analysis_id}/datasource/{datasource_id}')
def link_datasource(
    analysis_id: str,
    datasource_id: str,
    session: Session = Depends(get_db),
):
    """Link a datasource to an analysis."""
    try:
        service.link_datasource(session, analysis_id, datasource_id)
        return {'message': f'DataSource {datasource_id} linked to Analysis {analysis_id}'}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to link datasource: {str(e)}')


@router.delete('/{analysis_id}/datasources/{datasource_id}', status_code=204)
def unlink_datasource(
    analysis_id: str,
    datasource_id: str,
    session: Session = Depends(get_db),
):
    """Unlink a datasource from an analysis."""
    try:
        service.unlink_datasource(session, analysis_id, datasource_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to unlink datasource: {str(e)}')
