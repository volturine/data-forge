from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.analysis import schemas, service

router = APIRouter(prefix='/api/v1/analysis', tags=['analysis'])


@router.post('', response_model=schemas.AnalysisResponseSchema)
async def create_analysis(
    data: schemas.AnalysisCreateSchema,
    session: AsyncSession = Depends(get_db),
):
    """Create a new analysis with pipeline definition."""
    try:
        return await service.create_analysis(session, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to create analysis: {str(e)}')


@router.get('', response_model=list[schemas.AnalysisGalleryItemSchema])
async def list_analyses(session: AsyncSession = Depends(get_db)):
    """List all analyses as gallery items."""
    try:
        return await service.list_analyses(session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to list analyses: {str(e)}')


@router.get('/{analysis_id}', response_model=schemas.AnalysisResponseSchema)
async def get_analysis(
    analysis_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Get a specific analysis by ID."""
    try:
        return await service.get_analysis(session, analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get analysis: {str(e)}')


@router.put('/{analysis_id}', response_model=schemas.AnalysisResponseSchema)
async def update_analysis(
    analysis_id: str,
    data: schemas.AnalysisUpdateSchema,
    session: AsyncSession = Depends(get_db),
):
    """Update an existing analysis."""
    try:
        return await service.update_analysis(session, analysis_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to update analysis: {str(e)}')


@router.delete('/{analysis_id}')
async def delete_analysis(
    analysis_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Delete an analysis and its associations."""
    try:
        await service.delete_analysis(session, analysis_id)
        return {'message': f'Analysis {analysis_id} deleted successfully'}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to delete analysis: {str(e)}')


@router.post('/{analysis_id}/datasource/{datasource_id}')
async def link_datasource(
    analysis_id: str,
    datasource_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Link a datasource to an analysis."""
    try:
        await service.link_datasource(session, analysis_id, datasource_id)
        return {'message': f'DataSource {datasource_id} linked to Analysis {analysis_id}'}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to link datasource: {str(e)}')


@router.delete('/{analysis_id}/datasources/{datasource_id}', status_code=204)
async def unlink_datasource(
    analysis_id: str,
    datasource_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Unlink a datasource from an analysis."""
    try:
        await service.unlink_datasource(session, analysis_id, datasource_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to unlink datasource: {str(e)}')
