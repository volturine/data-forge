from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from modules.results import schemas, service

router = APIRouter(prefix='/results', tags=['results'])


@router.get('/{analysis_id}', response_model=schemas.ResultMetadataSchema)
async def get_result_metadata(analysis_id: str):
    """Get metadata for analysis result."""
    try:
        return await service.get_result_metadata(analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get result metadata: {str(e)}')


@router.get('/{analysis_id}/data', response_model=schemas.ResultDataSchema)
async def get_result_data(analysis_id: str, page: int = 1, page_size: int = 100):
    """Get paginated result data."""
    if page < 1:
        raise HTTPException(status_code=400, detail='Page must be >= 1')
    if page_size < 1 or page_size > 1000:
        raise HTTPException(status_code=400, detail='Page size must be between 1 and 1000')

    try:
        return await service.get_result_data(analysis_id, page, page_size)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get result data: {str(e)}')


@router.post('/{analysis_id}/export')
async def export_result(analysis_id: str, request: schemas.ExportRequestSchema):
    """Export result to requested format."""
    try:
        export_path = await service.export_result(analysis_id, request.format)
        return FileResponse(
            path=export_path,
            filename=f'{analysis_id}.{request.format}',
            media_type='application/octet-stream',
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to export result: {str(e)}')


@router.delete('/{analysis_id}')
async def delete_result(analysis_id: str):
    """Delete analysis result."""
    try:
        await service.delete_result(analysis_id)
        return {'message': f'Result {analysis_id} deleted successfully'}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to delete result: {str(e)}')
