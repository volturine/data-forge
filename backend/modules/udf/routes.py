from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from core.database import get_db
from core.validation import UdfId, parse_udf_id
from modules.udf import schemas, service

router = APIRouter(prefix='/udf', tags=['udf'])


@router.get('', response_model=list[schemas.UdfResponseSchema])
def list_udfs(
    q: str | None = Query(default=None),
    dtype_key: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    session: Session = Depends(get_db),
):
    return service.list_udfs(session, query=q, dtype_key=dtype_key, tag=tag)


@router.post('', response_model=schemas.UdfResponseSchema)
def create_udf(
    data: schemas.UdfCreateSchema,
    session: Session = Depends(get_db),
):
    try:
        return service.create_udf(session, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get('/match', response_model=list[schemas.UdfResponseSchema])
def match_udfs(
    dtypes: list[str] = Query(default=[]),
    session: Session = Depends(get_db),
):
    return service.match_udfs(session, dtypes)


@router.get('/export', response_model=schemas.UdfExportSchema)
def export_udfs(session: Session = Depends(get_db)):
    udfs = service.export_udfs(session)
    return schemas.UdfExportSchema(udfs=udfs)


@router.post('/import', response_model=list[schemas.UdfResponseSchema])
def import_udfs(
    data: schemas.UdfImportSchema,
    session: Session = Depends(get_db),
):
    try:
        return service.import_udfs(session, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get('/{udf_id}', response_model=schemas.UdfResponseSchema)
def get_udf(udf_id: UdfId, session: Session = Depends(get_db)):
    try:
        return service.get_udf(session, parse_udf_id(udf_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put('/{udf_id}', response_model=schemas.UdfResponseSchema)
def update_udf(
    udf_id: UdfId,
    data: schemas.UdfUpdateSchema,
    session: Session = Depends(get_db),
):
    try:
        return service.update_udf(session, parse_udf_id(udf_id), data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post('/{udf_id}/clone', response_model=schemas.UdfResponseSchema)
def clone_udf(
    udf_id: UdfId,
    data: schemas.UdfCloneSchema,
    session: Session = Depends(get_db),
):
    try:
        return service.clone_udf(session, parse_udf_id(udf_id), data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete('/{udf_id}', status_code=204)
def delete_udf(udf_id: UdfId, session: Session = Depends(get_db)):
    try:
        udf_id_value = parse_udf_id(udf_id)
        service.delete_udf(session, udf_id_value)
        return None
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
