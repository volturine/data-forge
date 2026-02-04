from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from core.database import get_db
from modules.udf import schemas, service

router = APIRouter(prefix='/udf', tags=['udf'])


@router.get('', response_model=list[schemas.UdfResponseSchema])
def list_udfs(
    q: str | None = Query(default=None),
    dtype_key: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    session: Session = Depends(get_db),
):
    try:
        return service.list_udfs(session, query=q, dtype_key=dtype_key, tag=tag)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to list UDFs: {str(e)}')


@router.post('', response_model=schemas.UdfResponseSchema)
def create_udf(
    data: schemas.UdfCreateSchema,
    session: Session = Depends(get_db),
):
    try:
        return service.create_udf(session, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to create UDF: {str(e)}')


@router.get('/match', response_model=list[schemas.UdfResponseSchema])
def match_udfs(
    dtypes: list[str] = Query(default=[]),
    session: Session = Depends(get_db),
):
    try:
        return service.match_udfs(session, dtypes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to match UDFs: {str(e)}')


@router.get('/export', response_model=schemas.UdfExportSchema)
def export_udfs(session: Session = Depends(get_db)):
    try:
        udfs = service.export_udfs(session)
        return schemas.UdfExportSchema(udfs=udfs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to export UDFs: {str(e)}')


@router.post('/import', response_model=list[schemas.UdfResponseSchema])
def import_udfs(
    data: schemas.UdfImportSchema,
    session: Session = Depends(get_db),
):
    try:
        return service.import_udfs(session, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to import UDFs: {str(e)}')


@router.get('/{udf_id}', response_model=schemas.UdfResponseSchema)
def get_udf(udf_id: str, session: Session = Depends(get_db)):
    try:
        return service.get_udf(session, udf_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get UDF: {str(e)}')


@router.put('/{udf_id}', response_model=schemas.UdfResponseSchema)
def update_udf(
    udf_id: str,
    data: schemas.UdfUpdateSchema,
    session: Session = Depends(get_db),
):
    try:
        return service.update_udf(session, udf_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to update UDF: {str(e)}')


@router.post('/{udf_id}/clone', response_model=schemas.UdfResponseSchema)
def clone_udf(
    udf_id: str,
    data: schemas.UdfCloneSchema,
    session: Session = Depends(get_db),
):
    try:
        return service.clone_udf(session, udf_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to clone UDF: {str(e)}')


@router.delete('/{udf_id}')
def delete_udf(udf_id: str, session: Session = Depends(get_db)):
    try:
        service.delete_udf(session, udf_id)
        return {'message': f'UDF {udf_id} deleted successfully'}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to delete UDF: {str(e)}')
